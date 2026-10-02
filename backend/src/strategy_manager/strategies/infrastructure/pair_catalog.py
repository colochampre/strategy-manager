"""Implements ``strategies.application.ports.PairCatalogPort``: which pairs a
capital pool's venue lists, read WITHOUT a credential (decision 41).

**No credential in the API process (rule 8).** Every source here is built on
the public transports, whose constructors take an HTTP client and nothing else.
There is no vault read, no cipher and no signer in this module, and a
structural test pins that. The reads are real, public, unsigned GETs in both
``DRY_RUN`` modes: the flag is not consulted, because validating a pair has to
be true before the system goes live, not after. No order and no account data
is involved.

**One entry per pool, never shared.** The cache key is the full
``(exchange, venue, settlement_currency)`` triple, so one pool's list can never
answer for another, even on the same venue. The registry is keyed
``(exchange, venue)``: Bybit and Binance both serve ``usdt-m``. A pool with no
registry entry (every Pionex pool: no public unsigned transport exists for it)
raises ``PairCatalogNotServed``. There is no fallback and no empty set, the
same rule as ``VenueExchangeRegistry``.

**Fail closed.** An expired entry is never served: the refresh either succeeds
or the call raises ``PairCatalogUnavailable``. A failure is never cached, so
the next request asks the venue again.

**One read per pool per TTL.** One ``asyncio.Lock`` per pool key, checked
before and after acquiring it, so two requests that miss together make ONE
venue call and the second reads the fresh entry. It is an in-process lock, not
a database lock: the caller holds no row lock and no advisory lock while it
waits here, so it cannot join a database lock cycle.

**What fails here without a log line?** A venue that cannot be read logs one
WARNING naming the pool, the error class and the venue's own code or HTTP
status, never a URL, a payload or the exception text (a venue error can quote
the request). The venue read itself logs its own INFO, WARNING and ERROR lines
(``shared.infrastructure.*.public_catalogue``). A cache hit logs nothing: it
would be one line per keystroke of the operator's work.

This is the only place that maps a venue symbol through ``market_key``.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import httpx

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.public_catalogue import (
    BinancePublicCatalogue,
)
from strategy_manager.shared.infrastructure.binance.transport import BinancePublicTransport
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.public_catalogue import BybitPublicCatalogue
from strategy_manager.shared.infrastructure.bybit.transport import BybitPublicTransport
from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
)

logger = logging.getLogger(__name__)

__all__ = ["CatalogueSource", "PerpetualSymbolSource", "VenuePairCatalog"]


class PerpetualSymbolSource(Protocol):
    """Venue-spelled symbols of every tradable perpetual a pool may use."""

    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class CatalogueSource:
    """A source and the one error type it raises when the venue cannot be
    read. Any other exception is a bug and is not translated."""

    symbols: PerpetualSymbolSource
    error_type: type[Exception]


class VenuePairCatalog:
    """The ``PairCatalogPort`` adapter: a registry, a TTL cache, single flight."""

    def __init__(
        self,
        sources: Mapping[tuple[str, str], CatalogueSource],
        ttl_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sources = sources
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        # ``PoolKey`` -> (pairs in market_key form, monotonic time of the read).
        # At most one entry per served pool: an unserved pool raises before
        # anything is stored, and the callers check the pool exists first.
        self._entries: dict[PoolKey, tuple[frozenset[str], float]] = {}
        self._locks: dict[PoolKey, asyncio.Lock] = {}

    @classmethod
    def for_settings(
        cls,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> "VenuePairCatalog":
        """The real wiring. ``transport`` and ``monotonic`` are the seams tests
        drive (``httpx.MockTransport`` and a fake clock); production passes
        neither."""
        return cls(
            {
                ("bybit", "usdt-m"): CatalogueSource(
                    _BybitSource(
                        settings.bybit_base_url,
                        settings.bybit_timeout_seconds,
                        transport,
                        monotonic,
                    ),
                    BybitApiError,
                ),
                ("binance", "usdt-m"): CatalogueSource(
                    _BinanceSource(
                        settings.binance_futures_base_url,
                        settings.binance_timeout_seconds,
                        transport,
                        monotonic,
                    ),
                    BinanceApiError,
                ),
            },
            settings.pair_catalogue_ttl_seconds,
            monotonic,
        )

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        exchange, venue, _ = pool
        source = self._sources.get((exchange, venue))
        if source is None:
            raise PairCatalogNotServed(
                f"no pair catalogue is served for {exchange}/{venue}"
            )

        cached = self._fresh(pool)
        if cached is not None:
            return cached

        async with self._locks.setdefault(pool, asyncio.Lock()):
            # A request that waited on the lock finds the first one's result.
            cached = self._fresh(pool)
            if cached is not None:
                return cached
            pairs = await self._read(source, pool)
            self._entries[pool] = (pairs, self._monotonic())
            return pairs

    def _fresh(self, pool: PoolKey) -> frozenset[str] | None:
        entry = self._entries.get(pool)
        if entry is None:
            return None
        pairs, read_at = entry
        if self._monotonic() - read_at < self._ttl_seconds:
            return pairs
        # Expired: dropped, so a refresh that fails can never fall back to it.
        del self._entries[pool]
        return None

    async def _read(self, source: CatalogueSource, pool: PoolKey) -> frozenset[str]:
        exchange, venue, currency = pool
        try:
            symbols = await source.symbols.tradable_perpetuals(currency)
        except source.error_type as exc:
            logger.warning(
                "pair catalogue unavailable: exchange=%s venue=%s settlement_currency=%s "
                "error=%s code=%s http_status=%s",
                exchange,
                venue,
                currency,
                type(exc).__name__,
                getattr(exc, "code", None),
                getattr(exc, "http_status", None),
            )
            raise PairCatalogUnavailable(
                f"the pair list of {exchange}/{venue} could not be read"
            ) from None
        return frozenset(market_key(symbol) for symbol in symbols)


class _BybitSource:
    """One public Bybit read per call. The client lives for that read only:
    reads are rare (at most one per pool per TTL), so nothing is kept open."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None,
        monotonic: Callable[[], float],
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._monotonic = monotonic

    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]:
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=self._transport
        ) as http:
            catalogue = BybitPublicCatalogue(BybitPublicTransport(http), monotonic=self._monotonic)
            return await catalogue.tradable_perpetuals(settlement_currency)


class _BinanceSource:
    """One public Binance USDⓈ-M read per call, same lifetime rule."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None,
        monotonic: Callable[[], float],
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._monotonic = monotonic

    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]:
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=self._transport
        ) as http:
            catalogue = BinancePublicCatalogue(
                BinancePublicTransport(http), monotonic=self._monotonic
            )
            return await catalogue.tradable_perpetuals(settlement_currency)

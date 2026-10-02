"""``VenuePairCatalog``: the registry, the ``market_key`` mapping, the cache.

The venue is a fake source and time is an injected callable, so nothing here
touches a network, waits on a clock or needs a credential. The concurrency
proof parks the source on an ``asyncio.Event`` and lets the event loop run
until the second caller can only be waiting on the per-pool lock.

Symbol spelling across the boundary: the fake venue lists ``STXUSDT_PERP`` (and
other spellings), the pool is asked for under no symbol at all, and the answer
is the ``market_key`` form ``STXUSDT`` that a save stores and accepts back.
"""

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
)
from strategy_manager.strategies.infrastructure.pair_catalog import (
    CatalogueSource,
    VenuePairCatalog,
)
from tests.shared.infrastructure.binance.test_futures_rules import AAVE
from tests.shared.infrastructure.bybit.test_read_client import BTC_PERP

TTL = 300.0
BYBIT_USDT = ("bybit", "usdt-m", "USDT")
BYBIT_USDC = ("bybit", "usdt-m", "USDC")
BINANCE_USDT = ("binance", "usdt-m", "USDT")
PIONEX_SPOT = ("pionex", "spot", "USDT")

LOGGER_NAME = "strategy_manager.strategies.infrastructure.pair_catalog"
SECRET_URL = "https://api.bybit.com/v5/market/instruments-info?category=linear"


class _VenueError(Exception):
    """Stands in for BybitApiError / BinanceApiError: carries a code and a
    status, and a message that quotes a URL the log must never repeat."""

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Source:
    """A venue that answers per settlement currency and records every read."""

    def __init__(self, listing: dict[str, tuple[str, ...]] | None = None) -> None:
        self.listing = listing if listing is not None else {"USDT": ("STXUSDT_PERP",)}
        self.reads: list[str] = []
        self.failure: Exception | None = None
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def tradable_perpetuals(self, settlement_currency: str) -> tuple[str, ...]:
        self.reads.append(settlement_currency)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        return self.listing.get(settlement_currency, ())


def _catalog(
    source: _Source, clock: _Clock, *, error_type: type[Exception] = _VenueError
) -> VenuePairCatalog:
    return VenuePairCatalog(
        {("bybit", "usdt-m"): CatalogueSource(source, error_type)}, TTL, clock
    )


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER_NAME and r.levelno == logging.WARNING]


async def test_venue_symbols_are_returned_in_market_key_form() -> None:
    source = _Source({"USDT": ("STXUSDT_PERP", "aaveusdt", "BTCUSDT.P")})

    result = await _catalog(source, _Clock()).available_pairs(BYBIT_USDT)

    assert result == frozenset({market_key("STXUSDT.P"), "AAVEUSDT", "BTCUSDT"})


async def test_a_pool_with_no_source_raises_not_served_and_never_an_empty_set() -> None:
    source = _Source()

    with pytest.raises(PairCatalogNotServed):
        await _catalog(source, _Clock()).available_pairs(PIONEX_SPOT)

    assert source.reads == []


async def test_a_venue_error_becomes_pair_catalog_unavailable_with_one_warning_and_no_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = _Source()
    source.failure = _VenueError(f"GET {SECRET_URL} failed", code="10016", http_status=503)
    caplog.set_level(logging.DEBUG, logger=LOGGER_NAME)

    with pytest.raises(PairCatalogUnavailable):
        await _catalog(source, _Clock()).available_pairs(BYBIT_USDT)

    [record] = _warnings(caplog)
    text = record.getMessage()
    for part in ("bybit", "usdt-m", "USDT", "_VenueError", "10016", "503"):
        assert part in text
    assert "http" not in text.replace("http_status", "")
    assert "instruments-info" not in text
    assert record.exc_info is None


async def test_an_error_that_is_not_the_venues_own_is_not_swallowed() -> None:
    source = _Source()
    source.failure = RuntimeError("a bug, not a venue answer")

    with pytest.raises(RuntimeError):
        await _catalog(source, _Clock()).available_pairs(BYBIT_USDT)


async def test_a_second_call_within_the_ttl_makes_no_venue_read() -> None:
    clock = _Clock()
    source = _Source()
    catalog = _catalog(source, clock)

    first = await catalog.available_pairs(BYBIT_USDT)
    clock.advance(TTL - 1)
    second = await catalog.available_pairs(BYBIT_USDT)

    assert source.reads == ["USDT"]
    assert first == second == frozenset({"STXUSDT"})


async def test_an_expired_entry_is_refetched() -> None:
    clock = _Clock()
    source = _Source()
    catalog = _catalog(source, clock)
    await catalog.available_pairs(BYBIT_USDT)

    clock.advance(TTL + 1)
    source.listing = {"USDT": ("STXUSDT_PERP", "NEWUSDT_PERP")}
    refreshed = await catalog.available_pairs(BYBIT_USDT)

    assert source.reads == ["USDT", "USDT"]
    assert refreshed == frozenset({"STXUSDT", "NEWUSDT"})


async def test_an_expired_entry_is_never_served_when_the_refresh_fails() -> None:
    clock = _Clock()
    source = _Source()
    catalog = _catalog(source, clock)
    await catalog.available_pairs(BYBIT_USDT)

    clock.advance(TTL + 1)
    source.failure = _VenueError("down", http_status=503)
    with pytest.raises(PairCatalogUnavailable):
        await catalog.available_pairs(BYBIT_USDT)

    # And the failed refresh did not resurrect the old entry either.
    with pytest.raises(PairCatalogUnavailable):
        await catalog.available_pairs(BYBIT_USDT)
    assert source.reads == ["USDT", "USDT", "USDT"]


async def test_a_failure_is_not_cached() -> None:
    source = _Source()
    source.failure = _VenueError("down", http_status=503)
    catalog = _catalog(source, _Clock())
    with pytest.raises(PairCatalogUnavailable):
        await catalog.available_pairs(BYBIT_USDT)

    source.failure = None
    recovered = await catalog.available_pairs(BYBIT_USDT)

    assert recovered == frozenset({"STXUSDT"})
    assert source.reads == ["USDT", "USDT"]


async def _let_the_loop_run(times: int = 50) -> None:
    """Yields to the event loop without a clock: every task that can make
    progress without an external event does, so whoever is still pending is
    waiting on something (here, the per-pool lock or the parked source)."""
    for _ in range(times):
        await asyncio.sleep(0)


async def test_concurrent_misses_make_one_venue_read() -> None:
    source = _Source()
    source.gate = asyncio.Event()
    catalog = _catalog(source, _Clock())

    first = asyncio.create_task(catalog.available_pairs(BYBIT_USDT))
    await source.entered.wait()
    second = asyncio.create_task(catalog.available_pairs(BYBIT_USDT))
    await _let_the_loop_run()

    # The second caller had every chance to reach the venue and did not: it is
    # waiting on the lock the first one holds, and the first one is parked.
    assert source.reads == ["USDT"]
    assert not first.done()
    assert not second.done()

    source.gate.set()
    results = await asyncio.gather(first, second)

    assert results[0] == results[1] == frozenset({"STXUSDT"})
    assert source.reads == ["USDT"]


async def test_each_pool_key_has_its_own_entry_and_its_own_settlement_currency_reaches_the_source() -> None:  # noqa: E501
    source = _Source({"USDT": ("STXUSDT_PERP",), "USDC": ("BTCUSDC_PERP",)})
    catalog = _catalog(source, _Clock())

    usdt = await catalog.available_pairs(BYBIT_USDT)
    usdc = await catalog.available_pairs(BYBIT_USDC)
    usdt_again = await catalog.available_pairs(BYBIT_USDT)
    usdc_again = await catalog.available_pairs(BYBIT_USDC)

    assert usdt == usdt_again == frozenset({"STXUSDT"})
    assert usdc == usdc_again == frozenset({"BTCUSDC"})
    assert source.reads == ["USDT", "USDC"]


async def test_one_exchanges_entry_never_answers_for_another_on_the_same_venue_name() -> None:
    bybit = _Source({"USDT": ("STXUSDT_PERP",)})
    binance = _Source({"USDT": ("AAVEUSDT",)})
    catalog = VenuePairCatalog(
        {
            ("bybit", "usdt-m"): CatalogueSource(bybit, _VenueError),
            ("binance", "usdt-m"): CatalogueSource(binance, _VenueError),
        },
        TTL,
        _Clock(),
    )

    assert await catalog.available_pairs(BYBIT_USDT) == frozenset({"STXUSDT"})
    assert await catalog.available_pairs(BINANCE_USDT) == frozenset({"AAVEUSDT"})
    assert bybit.reads == ["USDT"]
    assert binance.reads == ["USDT"]


def _settings(**overrides: Any) -> Settings:
    base: Settings = get_settings()
    return base.model_copy(
        update={
            "bybit_base_url": "https://bybit.example.test",
            "binance_futures_base_url": "https://binance.example.test",
            **overrides,
        }
    )


def _venues(recorded: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.host == "bybit.example.test":
            body: dict[str, Any] = {
                "retCode": 0,
                "result": {"list": [{**BTC_PERP, "symbol": "STXUSDT"}], "nextPageCursor": ""},
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"symbols": [AAVE]})

    return handler


async def test_for_settings_serves_both_usdt_m_pools_and_no_other() -> None:
    recorded: list[httpx.Request] = []
    catalog = VenuePairCatalog.for_settings(
        _settings(), transport=httpx.MockTransport(_venues(recorded))
    )

    assert await catalog.available_pairs(BYBIT_USDT) == frozenset({"STXUSDT"})
    assert await catalog.available_pairs(BINANCE_USDT) == frozenset({"AAVEUSDT"})
    with pytest.raises(PairCatalogNotServed):
        await catalog.available_pairs(PIONEX_SPOT)
    assert {r.url.host for r in recorded} == {"bybit.example.test", "binance.example.test"}


async def test_for_settings_takes_the_ttl_from_settings_and_the_default_is_five_minutes() -> None:
    assert Settings.model_fields["pair_catalogue_ttl_seconds"].default == 300.0

    recorded: list[httpx.Request] = []
    clock = _Clock()
    catalog = VenuePairCatalog.for_settings(
        _settings(pair_catalogue_ttl_seconds=10.0),
        transport=httpx.MockTransport(_venues(recorded)),
        monotonic=clock,
    )

    await catalog.available_pairs(BYBIT_USDT)
    clock.advance(9)
    await catalog.available_pairs(BYBIT_USDT)
    assert len(recorded) == 1

    clock.advance(2)
    await catalog.available_pairs(BYBIT_USDT)
    assert len(recorded) == 2


async def test_a_real_venue_failure_is_unavailable_for_both_venues() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(451 if request.url.host.startswith("binance") else 503)

    catalog = VenuePairCatalog.for_settings(
        _settings(), transport=httpx.MockTransport(refuse)
    )

    with pytest.raises(PairCatalogUnavailable):
        await catalog.available_pairs(BYBIT_USDT)
    with pytest.raises(PairCatalogUnavailable):
        await catalog.available_pairs(BINANCE_USDT)

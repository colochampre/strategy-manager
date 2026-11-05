"""The price a simulated fill prints at: the venue's own mark price, read from
its public market data (decision 35).

An alert's price is whatever its author typed into the alert, or whatever a
Heikin Ashi chart computed, so it never prices a simulated fill: a simulated
subscriber would read results no real fill could have had, and decides from
them whether to trade for real. The mark, not the last trade, for the reason the
live adapters size from it: one print on a thin book cannot move it.

Public endpoints, so a user with no key simulates too. Each read opens its own
HTTP client, as the pair catalogue's sources do, so nothing here outlives a
call. The answer is parsed by the same function the signed read client uses,
so the simulation refuses exactly what a live opening refuses.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Protocol

import httpx

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.money import Exchange
from strategy_manager.shared.infrastructure.binance.read_client import PREMIUM_INDEX_PATH
from strategy_manager.shared.infrastructure.binance.read_client import (
    parse_mark_price as parse_binance_mark_price,
)
from strategy_manager.shared.infrastructure.binance.transport import BinancePublicTransport
from strategy_manager.shared.infrastructure.bybit.catalogue_pages import LINEAR
from strategy_manager.shared.infrastructure.bybit.read_client import TICKERS_PATH
from strategy_manager.shared.infrastructure.bybit.read_client import (
    parse_mark_price as parse_bybit_mark_price,
)
from strategy_manager.shared.infrastructure.bybit.transport import BybitPublicTransport


class MarkPriceSource(Protocol):
    """The venue's mark price for one market, or the venue's own error."""

    async def mark_price(self, symbol: str) -> Decimal: ...


class BybitPublicMarkPrices:
    """Bybit's ``markPrice`` from ``/v5/market/tickers``, category linear."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def mark_price(self, symbol: str) -> Decimal:
        market = market_key(symbol)
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=self._transport
        ) as http:
            data = await BybitPublicTransport(http).get(
                TICKERS_PATH, {"category": LINEAR, "symbol": market}
            )
        return parse_bybit_mark_price(data, market)


class BinancePublicMarkPrices:
    """Binance's ``markPrice`` from ``/fapi/v1/premiumIndex``, IP weight 1."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def mark_price(self, symbol: str) -> Decimal:
        market = market_key(symbol)
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=self._transport
        ) as http:
            payload = await BinancePublicTransport(http).get(
                PREMIUM_INDEX_PATH, {"symbol": market}
            )
        return parse_binance_mark_price(payload, market)


def public_mark_prices(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> Mapping[str, MarkPriceSource]:
    """One public price source per exchange a simulated exchange exists for,
    each on the host its live adapter trades on. ``transport`` is for tests."""
    return {
        Exchange.BYBIT.value: BybitPublicMarkPrices(
            settings.bybit_base_url, settings.bybit_timeout_seconds, transport
        ),
        Exchange.BINANCE.value: BinancePublicMarkPrices(
            settings.binance_futures_base_url, settings.binance_timeout_seconds, transport
        ),
    }

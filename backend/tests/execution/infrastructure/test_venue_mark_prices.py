"""The public mark-price readers a simulated fill is priced with (decision 35).

Each one is driven over ``httpx.MockTransport``: no network, no credential
(rule 1). The symbol arrives in TradingView's spelling, ``STXUSDT.P``, and the
venue is asked for its bare ``STXUSDT``. Every refusal the parser owns is
pinned by the read clients' own tests; one per venue here proves the public
reader goes through that parser rather than a looser one of its own.
"""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.execution.infrastructure.venue_mark_prices import (
    BinancePublicMarkPrices,
    BybitPublicMarkPrices,
    public_mark_prices,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import PREMIUM_INDEX_PATH
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import TICKERS_PATH

TRADINGVIEW_SYMBOL = "STXUSDT.P"
VENUE_SYMBOL = "STXUSDT"


def _bybit_ticker(symbol: str = VENUE_SYMBOL, mark: str = "0.4633") -> dict[str, Any]:
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "linear",
            "list": [{"symbol": symbol, "lastPrice": "0.4700", "markPrice": mark}],
        },
    }


def _premium_index(symbol: str = VENUE_SYMBOL, mark: str = "0.4633") -> dict[str, Any]:
    return {"symbol": symbol, "markPrice": mark, "indexPrice": "0.4630"}


class Recorder:
    """Answers every request with one body and remembers what was asked."""

    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, content=json.dumps(self.body))

        return httpx.MockTransport(handle)


def _no_key_header(request: httpx.Request) -> bool:
    return not any(
        name.lower().startswith(("x-bapi", "x-mbx")) for name in request.headers
    )


async def test_bybit_reads_the_linear_mark_price_of_the_bare_symbol_with_no_key() -> None:
    venue = Recorder(_bybit_ticker())
    prices = BybitPublicMarkPrices("https://bybit.test", 5.0, venue.transport())

    assert await prices.mark_price(TRADINGVIEW_SYMBOL) == Decimal("0.4633")

    [request] = venue.requests
    assert request.url.path == TICKERS_PATH
    assert dict(request.url.params) == {"category": "linear", "symbol": VENUE_SYMBOL}
    assert request.url.host == "bybit.test"
    assert _no_key_header(request)
    assert "sign" not in request.url.query.decode()


async def test_bybit_refuses_another_symbols_ticker_rather_than_pricing_with_it() -> None:
    venue = Recorder(_bybit_ticker(symbol="BTCUSDT", mark="78055.30"))
    prices = BybitPublicMarkPrices("https://bybit.test", 5.0, venue.transport())

    with pytest.raises(BybitApiError):
        await prices.mark_price(TRADINGVIEW_SYMBOL)


async def test_binance_reads_the_premium_index_mark_price_of_the_bare_symbol_with_no_key() -> None:
    venue = Recorder(_premium_index())
    prices = BinancePublicMarkPrices("https://binance.test", 5.0, venue.transport())

    assert await prices.mark_price(TRADINGVIEW_SYMBOL) == Decimal("0.4633")

    [request] = venue.requests
    assert request.url.path == PREMIUM_INDEX_PATH
    assert dict(request.url.params) == {"symbol": VENUE_SYMBOL}
    assert request.url.host == "binance.test"
    assert _no_key_header(request)
    assert "signature" not in request.url.query.decode()


async def test_binance_refuses_a_zero_mark_price_rather_than_pricing_with_it() -> None:
    venue = Recorder(_premium_index(mark="0"))
    prices = BinancePublicMarkPrices("https://binance.test", 5.0, venue.transport())

    with pytest.raises(BinanceApiError):
        await prices.mark_price(TRADINGVIEW_SYMBOL)


async def test_production_reads_each_exchange_from_its_own_configured_host() -> None:
    settings = get_settings()
    asked: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        if request.url.path == TICKERS_PATH:
            return httpx.Response(200, content=json.dumps(_bybit_ticker(mark="0.46")))
        return httpx.Response(200, content=json.dumps(_premium_index(mark="0.47")))

    prices = public_mark_prices(settings, httpx.MockTransport(handle))

    assert sorted(prices) == ["binance", "bybit"]
    assert await prices["bybit"].mark_price(TRADINGVIEW_SYMBOL) == Decimal("0.46")
    assert await prices["binance"].mark_price(TRADINGVIEW_SYMBOL) == Decimal("0.47")
    bybit, binance = asked
    assert (bybit.url.host, bybit.url.path) == (
        httpx.URL(settings.bybit_base_url).host,
        TICKERS_PATH,
    )
    assert (binance.url.host, binance.url.path) == (
        httpx.URL(settings.binance_futures_base_url).host,
        PREMIUM_INDEX_PATH,
    )

"""The adapter behind the open positions' mark price (RD.3b): the venue's public
mark source, over ``httpx.MockTransport``. No network, no credential.

Symbols (rule R7): the port is asked for the market key ``STXUSDT``; the source
answers for the venue's bare name, and a source that answers for another market
is refused by the parser, not priced with.
"""

import asyncio
import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.execution.infrastructure.venue_mark_prices import (
    BinancePublicMarkPrices,
    BybitPublicMarkPrices,
)
from strategy_manager.performance.infrastructure.open_position_marks import (
    PublicOpenPositionMarks,
)
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError


def _bybit(mark: str = "0.4633", symbol: str = "STXUSDT") -> httpx.MockTransport:
    body: dict[str, Any] = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"category": "linear", "list": [{"symbol": symbol, "markPrice": mark}]},
    }
    return httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(body)))


def _binance(mark: str = "0.4701") -> httpx.MockTransport:
    body = {"symbol": "STXUSDT", "markPrice": mark, "indexPrice": "0.47"}
    return httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(body)))


def _marks(**sources: Any) -> PublicOpenPositionMarks:
    return PublicOpenPositionMarks(sources, timeout_seconds=1.0)


async def test_it_reads_each_exchange_from_its_own_public_source() -> None:
    marks = _marks(
        bybit=BybitPublicMarkPrices("https://bybit.test", 5.0, _bybit()),
        binance=BinancePublicMarkPrices("https://binance.test", 5.0, _binance()),
    )

    assert await marks.mark_price("bybit", "STXUSDT") == Decimal("0.4633")
    assert await marks.mark_price("binance", "STXUSDT") == Decimal("0.4701")


async def test_an_exchange_with_no_public_source_has_no_mark() -> None:
    marks = _marks(bybit=BybitPublicMarkPrices("https://bybit.test", 5.0, _bybit()))

    assert await marks.mark_price("pionex", "STXUSDT") is None


async def test_a_source_that_answers_for_another_market_is_refused() -> None:
    marks = _marks(
        bybit=BybitPublicMarkPrices("https://bybit.test", 5.0, _bybit(symbol="BTCUSDT"))
    )

    with pytest.raises(BybitApiError):
        await marks.mark_price("bybit", "STXUSDT")


async def test_a_source_that_does_not_answer_in_time_is_a_timeout() -> None:
    class _Hanging:
        async def mark_price(self, symbol: str) -> Decimal:
            await asyncio.sleep(5)
            return Decimal("1")

    marks = PublicOpenPositionMarks({"bybit": _Hanging()}, timeout_seconds=0.05)

    with pytest.raises(TimeoutError):
        await marks.mark_price("bybit", "STXUSDT")

"""The real adapters do not depend on the price of a close (decision 45;
spec: trade-execution § "A Real Adapter's Requests Do Not Depend On The Price
Of A Close").

``CloseOrderSpec.reference_price`` is read only by the simulated exchange. A
real adapter must not read it, send it, or let it change any order, size,
parameter or signature. The property that matters is on the WIRE, so each
REGISTERED adapter is driven through its REAL trade client over
``httpx.MockTransport`` with a frozen clock, and the requests produced with and
without a price are compared byte for byte: method, URL, query, body bytes,
headers (the signature included).

Three spellings cross the boundary: the alert's ``STXUSDT.P`` goes in, the
venue's bare ``STXUSDT`` must come out.
"""

import json
from dataclasses import dataclass, fields, replace
from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.execution.application.ports import CloseOrderSpec
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import MarketBuy, MarketSell, OrderSide
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.pionex_exchange import PionexExchangeAdapter
from strategy_manager.execution.infrastructure.pionex_futures_exchange import (
    PionexFuturesExchangeAdapter,
)
from strategy_manager.shared.infrastructure.binance.read_client import EXCHANGE_INFO_PATH
from strategy_manager.shared.infrastructure.binance.trade_client import (
    ORDER_PATH as BINANCE_ORDER_PATH,
)
from strategy_manager.shared.infrastructure.binance.trade_client import (
    POSITION_MODE_PATH as BINANCE_POSITION_MODE_PATH,
)
from strategy_manager.shared.infrastructure.binance.trade_client import BinanceTradeClient
from strategy_manager.shared.infrastructure.bybit.read_client import INSTRUMENTS_PATH
from strategy_manager.shared.infrastructure.bybit.signer import (
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    CREATE_ORDER_PATH as BYBIT_ORDER_PATH,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import BybitTradeClient
from tests.execution.infrastructure.test_binance_futures_exchange import (
    FakeTradeClient as BinanceFakeTradeClient,
)
from tests.execution.infrastructure.test_bybit_futures_exchange import (
    FakeTradeClient as BybitFakeTradeClient,
)
from tests.execution.infrastructure.test_pionex_exchange import (
    FakeTradeClient as PionexFakeTradeClient,
)
from tests.execution.infrastructure.test_pionex_futures_exchange import (
    FakeFuturesClient as PionexFakeFuturesClient,
)
from tests.shared.infrastructure.binance.test_futures_rules import AAVE
from tests.shared.infrastructure.binance.test_trade_client import _signer as binance_signer
from tests.shared.infrastructure.bybit.conftest import (
    API_KEY,
    API_SECRET,
    RECV_WINDOW,
    FrozenClock,
)
from tests.shared.infrastructure.bybit.test_read_client import BTC_PERP

CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
CLOSE_SIZE = Decimal("1250")

# The venue's bare spelling; TradingView sends ``STXUSDT.P``.
BYBIT_STX: dict[str, Any] = {**BTC_PERP, "symbol": "STXUSDT", "baseCoin": "STX"}
BINANCE_STX: dict[str, Any] = {**AAVE, "symbol": "STXUSDT", "baseAsset": "STX"}

PRICES = [Decimal("0.4633"), Decimal("9999999.5")]


@dataclass(frozen=True)
class SentRequest:
    method: str
    url: str
    query: bytes
    body: bytes
    headers: dict[str, str]


def _snapshot(request: httpx.Request) -> SentRequest:
    return SentRequest(
        method=request.method,
        url=str(request.url),
        query=request.url.query,
        body=request.content,
        headers=dict(request.headers),
    )


def _bybit_adapter(recorded: list[SentRequest]) -> BybitFuturesExchangeAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(_snapshot(request))
        if request.url.path == INSTRUMENTS_PATH:
            return httpx.Response(
                200,
                json={
                    "retCode": 0,
                    "retMsg": "OK",
                    "result": {
                        "list": [BYBIT_STX],
                        "category": "linear",
                        "nextPageCursor": "",
                    },
                },
            )
        assert request.url.path == BYBIT_ORDER_PATH
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "OK",
                "result": {"orderId": "BY-778899", "orderLinkId": CLIENT_ORDER_ID},
            },
        )

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(handler)
    )
    signer = BybitSigner(
        BybitCredentials(api_key=API_KEY, api_secret=API_SECRET),
        FrozenClock(),
        recv_window_ms=RECV_WINDOW,
    )
    return BybitFuturesExchangeAdapter(BybitTradeClient(http, signer))


def _binance_adapter(recorded: list[SentRequest]) -> BinanceFuturesExchangeAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(_snapshot(request))
        if request.method == "GET" and request.url.path == EXCHANGE_INFO_PATH:
            return httpx.Response(200, json={"symbols": [BINANCE_STX]})
        if request.method == "GET" and request.url.path == BINANCE_POSITION_MODE_PATH:
            # A close is only sent into a one-way account.
            return httpx.Response(200, json={"dualSidePosition": False})
        assert (request.method, request.url.path) == ("POST", BINANCE_ORDER_PATH)
        return httpx.Response(
            200,
            json={
                "orderId": 778899,
                "clientOrderId": CLIENT_ORDER_ID,
                "symbol": "STXUSDT",
                "status": "NEW",
            },
        )

    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(handler)
    )
    return BinanceFuturesExchangeAdapter(BinanceTradeClient(http, binance_signer()))


def _close_spec(reference_price: Decimal | None) -> CloseOrderSpec:
    return CloseOrderSpec(
        client_order_id=CLIENT_ORDER_ID,
        symbol="STXUSDT.P",
        side=OrderSide.SELL,
        base_size=CLOSE_SIZE,
        reference_price=reference_price,
    )


async def _build_and_place(
    adapter: BybitFuturesExchangeAdapter | BinanceFuturesExchangeAdapter,
    reference_price: Decimal | None,
) -> object:
    order = await adapter.build_close_order(_close_spec(reference_price))
    await adapter.place(order)
    return order


@pytest.mark.parametrize("price", PRICES)
async def test_bybit_close_requests_are_byte_identical_with_and_without_a_reference_price(
    price: Decimal,
) -> None:
    without: list[SentRequest] = []
    with_price: list[SentRequest] = []

    order_without = await _build_and_place(_bybit_adapter(without), None)
    order_with = await _build_and_place(_bybit_adapter(with_price), price)

    assert order_with == order_without
    assert len(with_price) == len(without) >= 2  # the instrument read and the order
    for sent, baseline in zip(with_price, without, strict=True):
        assert sent.method == baseline.method
        assert sent.url == baseline.url
        assert sent.query == baseline.query
        assert sent.body == baseline.body
        assert sent.headers == baseline.headers


@pytest.mark.parametrize("price", PRICES)
async def test_binance_close_requests_are_byte_identical_with_and_without_a_reference_price(
    price: Decimal,
) -> None:
    without: list[SentRequest] = []
    with_price: list[SentRequest] = []

    order_without = await _build_and_place(_binance_adapter(without), None)
    order_with = await _build_and_place(_binance_adapter(with_price), price)

    assert order_with == order_without
    assert len(with_price) == len(without) >= 2  # the instrument read and the order
    for sent, baseline in zip(with_price, without, strict=True):
        assert sent.method == baseline.method
        assert sent.url == baseline.url
        assert sent.query == baseline.query
        assert sent.body == baseline.body
        assert sent.headers == baseline.headers


async def test_each_request_names_the_bare_venue_symbol() -> None:
    bybit: list[SentRequest] = []
    binance: list[SentRequest] = []

    await _build_and_place(_bybit_adapter(bybit), Decimal("0.4633"))
    await _build_and_place(_binance_adapter(binance), Decimal("0.4633"))

    [bybit_post] = [r for r in bybit if r.method == "POST"]
    assert json.loads(bybit_post.body)["symbol"] == "STXUSDT"
    [binance_post] = [r for r in binance if r.method == "POST"]
    assert b"symbol=STXUSDT&" in binance_post.body
    # Never the alert's spelling, in any request of either run.
    for request in [*bybit, *binance]:
        assert b"STXUSDT.P" not in request.body
        assert b"STXUSDT.P" not in request.query
        assert "STXUSDT.P" not in request.url
        assert "STXUSDT%2EP" not in request.url


async def test_the_price_itself_appears_in_no_request() -> None:
    """A direct reading of the same property: neither the price nor its text
    is anywhere on the wire."""
    bybit: list[SentRequest] = []
    binance: list[SentRequest] = []

    await _build_and_place(_bybit_adapter(bybit), Decimal("9999999.5"))
    await _build_and_place(_binance_adapter(binance), Decimal("9999999.5"))

    assert len(bybit) >= 2 and len(binance) >= 2
    for request in [*bybit, *binance]:
        assert b"9999999.5" not in request.body
        assert "9999999.5" not in request.url


# ---- built orders and recorded client calls, for the four adapters that exist ----
#
# Each goes through the fake trade client its OWN suite defines, which records
# every call the adapter makes. The unregistered Pionex pair is covered here
# only (it has no wire test: nothing registers it), with its own spelling.


@pytest.mark.parametrize("price", PRICES)
async def test_bybit_builds_equal_orders_and_records_identical_calls_with_and_without_a_reference_price(  # noqa: E501
    price: Decimal,
) -> None:
    runs = []
    for reference_price in (None, price):
        client = BybitFakeTradeClient()
        adapter = BybitFuturesExchangeAdapter(client)  # type: ignore[arg-type]
        order = await adapter.build_close_order(_close_spec(reference_price))
        await adapter.place(order)
        runs.append((order, client.orders))

    assert runs[1][0] == runs[0][0]
    assert runs[1][1] == runs[0][1]
    assert len(runs[0][1]) == 1


@pytest.mark.parametrize("price", PRICES)
async def test_binance_builds_equal_orders_and_records_identical_calls_with_and_without_a_reference_price(  # noqa: E501
    price: Decimal,
) -> None:
    runs = []
    for reference_price in (None, price):
        client = BinanceFakeTradeClient()
        adapter = BinanceFuturesExchangeAdapter(client)  # type: ignore[arg-type]
        order = await adapter.build_close_order(_close_spec(reference_price))
        await adapter.place(order)
        runs.append((order, client.orders, client.leverage_reads, client.lookups))

    assert runs[1] == runs[0]
    assert len(runs[0][1]) == 1


@pytest.mark.parametrize("price", PRICES)
async def test_pionex_spot_builds_equal_orders_and_records_identical_calls_with_and_without_a_reference_price(  # noqa: E501
    price: Decimal,
) -> None:
    runs = []
    for reference_price in (None, price):
        client = PionexFakeTradeClient()
        adapter = PionexExchangeAdapter(client)  # type: ignore[arg-type]
        spec = replace(_close_spec(reference_price), symbol="STXUSDT_PERP")
        order = await adapter.build_close_order(spec)
        await adapter.place(order)
        runs.append((order, client.sells, client.buys))

    assert runs[1] == runs[0]
    assert len(runs[0][1]) == 1


@pytest.mark.parametrize("price", PRICES)
async def test_pionex_futures_builds_equal_orders_and_records_identical_calls_with_and_without_a_reference_price(  # noqa: E501
    price: Decimal,
) -> None:
    runs = []
    for reference_price in (None, price):
        client = PionexFakeFuturesClient()
        adapter = PionexFuturesExchangeAdapter(client)  # type: ignore[arg-type]
        spec = replace(_close_spec(reference_price), symbol="STXUSDT_PERP")
        order = await adapter.build_close_order(spec)
        await adapter.place(order)
        runs.append((order, client.orders))

    assert runs[1] == runs[0]
    [recorded] = runs[0][1]
    # The client's own ``reference_price`` is the venue's minimum-notional
    # guard, a different thing: a close has none, whatever the spec carried.
    assert recorded["reference_price"] is None


def test_no_order_type_a_real_adapter_sends_carries_a_price() -> None:
    """The reference price cannot ride on the order, so it cannot be sent: no
    order type has a place to put it. A price on an order is one edit away
    from a limit order."""
    for order_type in (MarketBuy, MarketSell, FuturesMarketOrder):
        names = {field.name for field in fields(order_type)}
        assert names, order_type
        assert "price" not in names
        assert "reference_price" not in names

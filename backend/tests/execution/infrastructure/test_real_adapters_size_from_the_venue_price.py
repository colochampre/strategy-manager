"""A live opening is sized from the venue's price, never the alert's (decision
35; tasks.md G.9).

The property that matters is the quantity on the WIRE, so each registered
adapter is driven through its REAL trade client over ``httpx.MockTransport``.
The alert carries a tenth of the market price, which is what an author who
wanted to open every live subscriber at ten times their margin would post.

Three spellings cross the boundary: the alert's ``STXUSDT.P`` goes in, the
venue's bare ``STXUSDT`` must come out, on the price read as on the order.
"""

import json
from decimal import Decimal
from urllib.parse import parse_qsl

import httpx

from strategy_manager.execution.application.ports import OpenOrderSpec
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.binance_futures_exchange import (
    BinanceFuturesExchangeAdapter,
)
from strategy_manager.execution.infrastructure.bybit_futures_exchange import (
    BybitFuturesExchangeAdapter,
)
from strategy_manager.shared.domain.leverage import Leverage
from strategy_manager.shared.infrastructure.binance.read_client import (
    EXCHANGE_INFO_PATH,
    PREMIUM_INDEX_PATH,
    SYMBOL_CONFIG_PATH,
)
from strategy_manager.shared.infrastructure.binance.trade_client import (
    ACCOUNT_CONFIG_PATH as BINANCE_ACCOUNT_CONFIG_PATH,
)
from strategy_manager.shared.infrastructure.binance.trade_client import (
    ORDER_PATH as BINANCE_ORDER_PATH,
)
from strategy_manager.shared.infrastructure.binance.trade_client import BinanceTradeClient
from strategy_manager.shared.infrastructure.bybit.read_client import (
    ACCOUNT_INFO_PATH as BYBIT_ACCOUNT_INFO_PATH,
)
from strategy_manager.shared.infrastructure.bybit.read_client import (
    INSTRUMENTS_PATH,
    POSITIONS_PATH,
    TICKERS_PATH,
)
from strategy_manager.shared.infrastructure.bybit.signer import (
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    CREATE_ORDER_PATH as BYBIT_ORDER_PATH,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import BybitTradeClient
from tests.execution.infrastructure.test_real_adapters_ignore_reference_price import (
    BINANCE_STX,
    BYBIT_STX,
)
from tests.shared.infrastructure.binance.test_trade_client import _signer as binance_signer
from tests.shared.infrastructure.bybit.conftest import (
    API_KEY,
    API_SECRET,
    RECV_WINDOW,
    FrozenClock,
)

CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
VENUE_PRICE = "0.4633"
ALERT_PRICE = Decimal("0.04633")
GRANTED = Decimal("20")

# 20 USDT of margin at 3x is 60 USDT of notional: 129.5056 STX at the venue's
# 0.4633, truncated to the contract's step. At the alert's price it would be
# ten times that, 1295.05, and every number below would be wrong by the same
# multiple.
BINANCE_QTY = Decimal("129.5")  # step 0.1
BYBIT_QTY = Decimal("129.505")  # step 0.001


def _open() -> OpenOrderSpec:
    return OpenOrderSpec(
        client_order_id=CLIENT_ORDER_ID,
        symbol="STXUSDT.P",
        side=OrderSide.BUY,
        granted=GRANTED,
        price=ALERT_PRICE,
        # The pair already holds it, so the Binance opening writes no setting.
        leverage=Leverage(3),
    )


def _bybit_adapter(recorded: list[httpx.Request]) -> BybitFuturesExchangeAdapter:
    def envelope(result: object) -> httpx.Response:
        return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": result})

    responses = {
        # A flat STX record at the 3x the spec asks, so no setting is written.
        ("GET", POSITIONS_PATH): envelope(
            {
                "list": [
                    {
                        "symbol": "STXUSDT",
                        "side": "",
                        "size": "0",
                        "avgPrice": "0",
                        "leverage": "3",
                        "positionIdx": 0,
                    }
                ]
            }
        ),
        ("GET", BYBIT_ACCOUNT_INFO_PATH): envelope({"marginMode": "ISOLATED_MARGIN"}),
        ("GET", INSTRUMENTS_PATH): envelope(
            {"list": [BYBIT_STX], "category": "linear", "nextPageCursor": ""}
        ),
        ("GET", TICKERS_PATH): envelope(
            {
                "category": "linear",
                "list": [
                    {
                        "symbol": "STXUSDT",
                        "lastPrice": "0.4630",
                        "markPrice": VENUE_PRICE,
                        "indexPrice": "0.4631",
                    }
                ],
            }
        ),
        ("POST", BYBIT_ORDER_PATH): envelope(
            {"orderId": "BY-778899", "orderLinkId": CLIENT_ORDER_ID}
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return responses[(request.method, request.url.path)]

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(handler)
    )
    signer = BybitSigner(
        BybitCredentials(api_key=API_KEY, api_secret=API_SECRET),
        FrozenClock(),
        recv_window_ms=RECV_WINDOW,
    )
    return BybitFuturesExchangeAdapter(BybitTradeClient(http, signer))


def _binance_adapter(recorded: list[httpx.Request]) -> BinanceFuturesExchangeAdapter:
    responses = {
        ("GET", SYMBOL_CONFIG_PATH): httpx.Response(
            200,
            json=[
                {
                    "symbol": "STXUSDT",
                    "leverage": 3,
                    "marginType": "ISOLATED",
                    "isAutoAddMargin": False,
                }
            ],
        ),
        ("GET", EXCHANGE_INFO_PATH): httpx.Response(200, json={"symbols": [BINANCE_STX]}),
        ("GET", PREMIUM_INDEX_PATH): httpx.Response(
            200,
            json={"symbol": "STXUSDT", "markPrice": VENUE_PRICE, "indexPrice": "0.4631"},
        ),
        ("GET", BINANCE_ACCOUNT_CONFIG_PATH): httpx.Response(
            200, json={"dualSidePosition": False}
        ),
        ("POST", BINANCE_ORDER_PATH): httpx.Response(
            200,
            json={
                "orderId": 778899,
                "clientOrderId": CLIENT_ORDER_ID,
                "symbol": "STXUSDT",
                "status": "NEW",
            },
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return responses[(request.method, request.url.path)]

    http = httpx.AsyncClient(
        base_url="https://fapi.binance.com", transport=httpx.MockTransport(handler)
    )
    return BinanceFuturesExchangeAdapter(BinanceTradeClient(http, binance_signer()))


def _paths(recorded: list[httpx.Request]) -> list[str]:
    return [request.url.path for request in recorded]


async def test_bybit_sends_the_quantity_the_venues_price_sizes() -> None:
    recorded: list[httpx.Request] = []
    adapter = _bybit_adapter(recorded)

    await adapter.place(await adapter.build_open_order(_open()))

    assert TICKERS_PATH in _paths(recorded)
    [posted] = [request for request in recorded if request.method == "POST"]
    assert Decimal(json.loads(posted.content)["qty"]) == BYBIT_QTY
    [ticker] = [request for request in recorded if request.url.path == TICKERS_PATH]
    assert ticker.url.params["symbol"] == "STXUSDT"
    # The price is read before the order goes, never after.
    assert _paths(recorded).index(TICKERS_PATH) < _paths(recorded).index(BYBIT_ORDER_PATH)


async def test_binance_sends_the_quantity_the_venues_price_sizes() -> None:
    recorded: list[httpx.Request] = []
    adapter = _binance_adapter(recorded)

    await adapter.place(await adapter.build_open_order(_open()))

    assert PREMIUM_INDEX_PATH in _paths(recorded)
    [posted] = [request for request in recorded if request.method == "POST"]
    assert Decimal(dict(parse_qsl(posted.content.decode()))["quantity"]) == BINANCE_QTY
    [index] = [request for request in recorded if request.url.path == PREMIUM_INDEX_PATH]
    assert index.url.params["symbol"] == "STXUSDT"
    assert _paths(recorded).index(PREMIUM_INDEX_PATH) < _paths(recorded).index(
        BINANCE_ORDER_PATH
    )

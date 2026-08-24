"""The futures trade client: the class that can move money on /uapi/v1/."""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.pionex.errors import (
    PionexApiError,
    PionexOrderNotFound,
)
from strategy_manager.shared.infrastructure.pionex.futures_read_client import (
    POSITION_MODE_PATH,
)
from strategy_manager.shared.infrastructure.pionex.futures_trade_client import (
    FILLS_BY_ORDER_ID_PATH,
    NEW_ORDER_PATH,
    ORDER_BY_CLIENT_ORDER_ID_PATH,
    PionexFuturesTradeClient,
)
from strategy_manager.shared.infrastructure.pionex.perp_symbols import SYMBOLS_PATH
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner
from tests.shared.infrastructure.pionex.test_perp_symbols import BTC_PERP

CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
SYMBOL = "BTC_USDT_PERP"
PRICE = Decimal("64000")


def _ok(data: Any) -> dict[str, Any]:
    return {"result": True, "timestamp": 1787313600000, "data": data}


def _client(
    signer: PionexSigner,
    recorded: list[httpx.Request],
    *,
    position_mode: str = "BUYSELL",
    order_response: dict[str, Any] | None = None,
    overrides: dict[str, httpx.Response] | None = None,
) -> PionexFuturesTradeClient:
    responses: dict[str, httpx.Response] = {
        SYMBOLS_PATH: httpx.Response(200, json=_ok({"symbols": [BTC_PERP]})),
        POSITION_MODE_PATH: httpx.Response(
            200, json=_ok({"positionMode": position_mode})
        ),
        NEW_ORDER_PATH: httpx.Response(
            200, json=_ok(order_response or {"orderId": 778899})
        ),
    }
    responses.update(overrides or {})

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return responses[request.url.path]

    http = httpx.AsyncClient(
        base_url="https://api.pionex.com",
        transport=httpx.MockTransport(handler),
    )
    return PionexFuturesTradeClient(http, signer)


def _sent_order(recorded: list[httpx.Request]) -> dict[str, Any]:
    posted = [r for r in recorded if r.method == "POST"]
    assert len(posted) == 1
    body: dict[str, Any] = json.loads(posted[0].content.decode())
    return body


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


async def test_an_order_is_sent_as_market_qty_sized_in_the_base_currency(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded)

    ack = await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="BUY",
        base_size=Decimal("0.0078"),
        reduce_only=False,
        reference_price=PRICE,
    )

    body = _sent_order(recorded)
    assert body["type"] == "MARKET_QTY"
    assert body["size"] == "0.0078"
    assert body["side"] == "BUY"
    assert body["reduceOnly"] is False
    assert body["clientOrderId"] == CLIENT_ORDER_ID
    assert ack.order_id == "778899"


async def test_a_sell_is_sent_in_the_same_denomination_as_a_buy(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The reason futures needs its own order type: there is no ``amount``
    field to get wrong, because MARKET_QTY is base-sized on both sides."""
    client = _client(signer, recorded)

    await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="SELL",
        base_size=Decimal("0.0078"),
        reduce_only=False,
        reference_price=PRICE,
    )

    body = _sent_order(recorded)
    assert body["side"] == "SELL"
    assert body["size"] == "0.0078"
    assert "amount" not in body


async def test_position_side_is_not_sent_in_one_way_mode(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The reference requires ``positionSide`` only for hedge mode, and hedge
    mode is refused outright."""
    client = _client(signer, recorded)

    await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="BUY",
        base_size=Decimal("0.0078"),
        reduce_only=False,
        reference_price=PRICE,
    )

    assert "positionSide" not in _sent_order(recorded)


async def test_a_close_carries_reduce_only(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded)

    await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="SELL",
        base_size=Decimal("0.0078"),
        reduce_only=True,
        reference_price=PRICE,
    )

    assert _sent_order(recorded)["reduceOnly"] is True


async def test_a_hedged_account_is_refused_before_any_order_is_sent(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """In hedge mode a symbol holds a long AND a short, and ``reduceOnly``
    stops protecting a close -- every close could open a fresh position on
    the other side."""
    client = _client(signer, recorded, position_mode="OPENCLOSE")

    with pytest.raises(PionexApiError, match="OPENCLOSE mode"):
        await client.place_market_order(
            symbol=SYMBOL,
            client_order_id=CLIENT_ORDER_ID,
            side="BUY",
            base_size=Decimal("0.0078"),
            reduce_only=False,
            reference_price=PRICE,
        )

    assert [r for r in recorded if r.method == "POST"] == []


async def test_the_position_mode_is_read_once_per_client(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """It is an account setting and the client is built per job, so
    re-reading it would add a round trip to the hot path for a number that
    cannot change inside one job."""
    client = _client(signer, recorded)

    for _ in range(2):
        await client.place_market_order(
            symbol=SYMBOL,
            client_order_id=CLIENT_ORDER_ID,
            side="BUY",
            base_size=Decimal("0.0078"),
            reduce_only=False,
            reference_price=PRICE,
        )

    mode_reads = [r for r in recorded if r.url.path == POSITION_MODE_PATH]
    assert len(mode_reads) == 1


async def test_the_size_is_truncated_to_the_step_before_it_is_sent(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded)

    await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="BUY",
        base_size=Decimal("0.00789123456"),
        reduce_only=False,
        reference_price=PRICE,
    )

    assert _sent_order(recorded)["size"] == "0.0078"


async def test_a_size_is_never_sent_in_scientific_notation(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """A futures size is always a quotient, so an exponent is not an edge
    case here -- it is the normal output of the sizing rule."""
    client = _client(signer, recorded, overrides={
        SYMBOLS_PATH: httpx.Response(
            200,
            json=_ok({"symbols": [{**BTC_PERP, "baseStep": "0.00000001",
                                   "minSizeMarket": "0.00000001",
                                   "minNotional": "0"}]}),
        )
    })

    await client.place_market_order(
        symbol=SYMBOL,
        client_order_id=CLIENT_ORDER_ID,
        side="BUY",
        base_size=Decimal("1E-8"),
        reduce_only=False,
        reference_price=PRICE,
    )

    assert _sent_order(recorded)["size"] == "0.00000001"


async def test_an_order_that_rounds_away_to_nothing_is_refused(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded)

    with pytest.raises(PionexApiError, match="nothing left to send"):
        await client.place_market_order(
            symbol=SYMBOL,
            client_order_id=CLIENT_ORDER_ID,
            side="BUY",
            base_size=Decimal("0.00001"),
            reduce_only=False,
            reference_price=PRICE,
        )

    assert [r for r in recorded if r.method == "POST"] == []


async def test_a_malformed_client_order_id_never_reaches_the_venue(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded)

    with pytest.raises(PionexApiError, match="letters, numbers and hyphens"):
        await client.place_market_order(
            symbol=SYMBOL,
            client_order_id="not a valid id!",
            side="BUY",
            base_size=Decimal("0.0078"),
            reduce_only=False,
            reference_price=PRICE,
        )


async def test_a_mismatched_client_order_id_echo_is_refused(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """If the echoed id is not ours, the handle this system uses to recover
    the order names an order Pionex did not create."""
    client = _client(
        signer,
        recorded,
        order_response={"orderId": 778899, "clientOrderId": "somebody-elses-id"},
    )

    with pytest.raises(PionexApiError, match="cannot be tracked by our own id"):
        await client.place_market_order(
            symbol=SYMBOL,
            client_order_id=CLIENT_ORDER_ID,
            side="BUY",
            base_size=Decimal("0.0078"),
            reduce_only=False,
            reference_price=PRICE,
        )


async def test_an_order_with_no_id_is_refused(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded, order_response={"accepted": True})

    with pytest.raises(PionexApiError, match="no orderId"):
        await client.place_market_order(
            symbol=SYMBOL,
            client_order_id=CLIENT_ORDER_ID,
            side="BUY",
            base_size=Decimal("0.0078"),
            reduce_only=False,
            reference_price=PRICE,
        )


async def test_a_not_found_code_becomes_order_not_found(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """VERIFIED live 2026-08-24: the futures API answers a lookup for an id
    no order carries with HTTP 200 and TRADE_ORDER_NOT_EXIST in the
    envelope."""
    client = _client(signer, recorded, overrides={
        ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(
            200,
            json={
                "result": False,
                "code": "TRADE_ORDER_NOT_EXIST",
                "message": "order not found",
            },
        )
    })

    with pytest.raises(PionexOrderNotFound):
        await client.order_id_for(CLIENT_ORDER_ID)


async def test_an_unlisted_rejection_code_stays_a_failed_call(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """The asymmetry that protects a live position: a failed lookup read as
    "no such order" releases the capital behind a real trade."""
    client = _client(signer, recorded, overrides={
        ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(
            200,
            json={"result": False, "code": "RATE_LIMIT", "message": "slow down"},
        )
    })

    with pytest.raises(PionexApiError):
        await client.order_id_for(CLIENT_ORDER_ID)


async def test_an_empty_lookup_result_is_the_not_found_answer(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, recorded, overrides={
        ORDER_BY_CLIENT_ORDER_ID_PATH: httpx.Response(200, json=_ok({}))
    })

    with pytest.raises(PionexOrderNotFound):
        await client.order_id_for(CLIENT_ORDER_ID)


async def test_fills_are_read_by_exchange_order_id(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    fill = {
        "id": 5150,
        "orderId": 778899,
        "symbol": SYMBOL,
        "side": "BUY",
        "role": "TAKER",
        "price": "64012.3",
        "size": "0.0078",
        "fee": "0.2496",
        "feeCoin": "USDT",
        "feeType": "TRADING",
        "timestamp": 1787313600000,
    }
    client = _client(signer, recorded, overrides={
        FILLS_BY_ORDER_ID_PATH: httpx.Response(200, json=_ok({"fills": [fill]}))
    })

    fills = await client.fills_for_order("778899")

    assert recorded[0].url.params["orderId"] == "778899"
    assert fills[0].price == Decimal("64012.3")
    assert fills[0].size == Decimal("0.0078")
    assert fills[0].fee_coin == "USDT"


async def test_no_fills_yet_is_an_empty_list_not_an_error(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """Accepted but unpublished is a legitimate transient state; the settle
    job retries rather than concluding the order did not fill."""
    client = _client(signer, recorded, overrides={
        FILLS_BY_ORDER_ID_PATH: httpx.Response(200, json=_ok({"fills": []}))
    })

    assert await client.fills_for_order("778899") == []

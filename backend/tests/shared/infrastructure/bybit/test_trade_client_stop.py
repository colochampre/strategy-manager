"""The protective stop on the Bybit trade client (subscriber-safety SS.5).

An opening order carries its own stop (``stopLoss`` with the three fields that make it a
Market stop on the whole position), so there is never a moment in which the position
exists without it. The stop that rests afterwards is found by ``parentOrderLinkId``, the
opening's ``orderLinkId``, among the conditional orders of the symbol.
"""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.signer import BybitSigner
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    CREATE_ORDER_PATH,
    OPEN_ORDERS_PATH,
    BybitTradeClient,
)

SYMBOL = "DOGEUSDT"
OPENING = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
OTHER_OPENING = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"


def _client(
    signer: BybitSigner, result: dict[str, Any], recorded: list[httpx.Request]
) -> BybitTradeClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(
            200, json={"retCode": 0, "retMsg": "OK", "result": result, "time": 1}
        )

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(handler)
    )
    return BybitTradeClient(http, signer)


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


def _created(recorded: list[httpx.Request]) -> dict[str, Any]:
    [posted] = recorded
    assert posted.method == "POST"
    assert posted.url.path == CREATE_ORDER_PATH
    body: dict[str, Any] = json.loads(posted.content)
    return body


async def test_an_opening_with_a_stop_carries_the_four_stop_fields(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {"orderId": "BY-1", "orderLinkId": OPENING}, recorded)

    await client.place_market_order(
        symbol=SYMBOL,
        order_link_id=OPENING,
        side="Buy",
        qty=Decimal("76"),
        reduce_only=False,
        stop_loss=Decimal("72.00"),
    )

    body = _created(recorded)
    assert body["stopLoss"] == "72.00"
    assert body["slTriggerBy"] == "MarkPrice"
    assert body["tpslMode"] == "Full"
    assert body["slOrderType"] == "Market"
    # Everything the adapter already sent is still sent, unchanged.
    assert body["reduceOnly"] is False
    assert body["positionIdx"] == 0
    assert body["orderLinkId"] == OPENING


async def test_an_order_without_a_stop_carries_none_of_the_stop_fields(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """A close, and every opening placed before a stop was attached, sends exactly the
    payload it always did."""
    client = _client(signer, {"orderId": "BY-1", "orderLinkId": OPENING}, recorded)

    await client.place_market_order(
        symbol=SYMBOL,
        order_link_id=OPENING,
        side="Sell",
        qty=Decimal("76"),
        reduce_only=True,
    )

    assert _created(recorded) == {
        "category": "linear",
        "symbol": SYMBOL,
        "side": "Sell",
        "orderType": "Market",
        "qty": "76",
        "orderLinkId": OPENING,
        "positionIdx": 0,
        "reduceOnly": True,
    }


def _stop(order_id: str, parent: str) -> dict[str, str]:
    return {
        "orderId": order_id,
        "parentOrderLinkId": parent,
        "stopOrderType": "StopLoss",
        "orderStatus": "Untriggered",
    }


async def test_the_resting_stop_is_the_conditional_order_whose_parent_is_the_opening(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Matched client-side and by the parent's id, never by position in the list: the
    first entry is another opening's stop on the same symbol."""
    client = _client(
        signer,
        {"list": [_stop("STOP-OTHER", OTHER_OPENING), _stop("STOP-1", OPENING)]},
        recorded,
    )

    found = await client.resting_stop_for(SYMBOL, OPENING)

    assert found == "STOP-1"
    [request] = recorded
    assert request.method == "GET"
    assert request.url.path == OPEN_ORDERS_PATH
    assert dict(request.url.params) == {
        "category": "linear",
        "symbol": SYMBOL,
        "orderFilter": "StopOrder",
    }


async def test_no_stop_for_the_opening_is_none_not_an_error(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {"list": [_stop("STOP-OTHER", OTHER_OPENING)]}, recorded)

    assert await client.resting_stop_for(SYMBOL, OPENING) is None


async def test_an_empty_list_is_none(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, {"list": []}, recorded)

    assert await client.resting_stop_for(SYMBOL, OPENING) is None


async def test_an_answer_with_no_list_is_an_error_not_an_absent_stop(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """Reading a malformed answer as "no stop" would close a protected position."""
    client = _client(signer, {}, recorded)

    with pytest.raises(BybitApiError):
        await client.resting_stop_for(SYMBOL, OPENING)

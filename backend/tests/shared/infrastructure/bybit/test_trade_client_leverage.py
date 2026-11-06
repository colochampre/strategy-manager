"""The one account setting the Bybit trade client writes: a symbol's leverage
(decision 38). The margin mode is account-wide on a Unified Trading Account,
so it is read and never written."""

import json
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.signer import (
    SIGNATURE_HEADER,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import (
    SET_LEVERAGE_PATH,
    BybitTradeClient,
)

SYMBOL = "SOLUSDT"


def _client(
    signer: BybitSigner, response: httpx.Response, recorded: list[httpx.Request]
) -> BybitTradeClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return response

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com", transport=httpx.MockTransport(handler)
    )
    return BybitTradeClient(http, signer)


def _answer(ret_code: int, ret_msg: str = "OK") -> httpx.Response:
    return httpx.Response(
        200, json={"retCode": ret_code, "retMsg": ret_msg, "result": {}, "time": 1}
    )


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


async def test_the_leverage_is_written_for_both_sides_of_a_one_way_symbol(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """In one-way mode Bybit requires ``buyLeverage`` and ``sellLeverage``
    to be equal."""
    client = _client(signer, _answer(0), recorded)

    await client.set_leverage(SYMBOL, 5)

    [posted] = recorded
    assert posted.method == "POST"
    assert posted.url.path == SET_LEVERAGE_PATH
    body: dict[str, Any] = json.loads(posted.content)
    assert body == {
        "category": "linear",
        "symbol": SYMBOL,
        "buyLeverage": "5",
        "sellLeverage": "5",
    }
    assert len(posted.headers[SIGNATURE_HEADER]) == 64


async def test_a_leverage_already_set_is_not_a_refusal(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    """110043 is "leverage not modified": what was asked already holds."""
    client = _client(signer, _answer(110043, "leverage not modified"), recorded)

    await client.set_leverage(SYMBOL, 5)


async def test_any_other_refusal_keeps_its_code(
    signer: BybitSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, _answer(10001, "leverage invalid"), recorded)

    with pytest.raises(BybitApiError) as caught:
        await client.set_leverage(SYMBOL, 5)

    assert caught.value.code == "10001"


@pytest.mark.parametrize("leverage", [0, 21, True])
async def test_a_leverage_outside_one_to_twenty_never_reaches_the_venue(
    signer: BybitSigner, recorded: list[httpx.Request], leverage: int
) -> None:
    client = _client(signer, _answer(0), recorded)

    with pytest.raises(BybitApiError, match="leverage"):
        await client.set_leverage(SYMBOL, leverage)

    assert recorded == []

from decimal import Decimal
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.read_client import (
    FUTURES_BALANCES_PATH,
    SPOT_BALANCES_PATH,
    PionexReadOnlyClient,
)
from strategy_manager.shared.infrastructure.pionex.signer import (
    KEY_HEADER,
    SIGNATURE_HEADER,
    PionexSigner,
)

SPOT_PAYLOAD: dict[str, Any] = {
    "result": True,
    "timestamp": 1787313600000,
    "data": {
        "balances": [
            {"coin": "USDT", "free": "12345.67891234", "frozen": "0.00000001"},
            {"coin": "BTC", "free": "0.10000000", "frozen": "0.00000000"},
        ]
    },
}

FUTURES_PAYLOAD: dict[str, Any] = {
    "result": True,
    "timestamp": 1787313600000,
    "data": {
        "balances": [
            {
                "coin": "USDT",
                "free": "500.00000000",
                "frozen": "25.50000000",
                "debts": "0.00000000",
            }
        ]
    },
}


def _client(
    signer: PionexSigner,
    response: httpx.Response,
    recorded: list[httpx.Request],
) -> PionexReadOnlyClient:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return response

    http = httpx.AsyncClient(
        base_url="https://api.pionex.com",
        transport=httpx.MockTransport(handler),
    )
    return PionexReadOnlyClient(http, signer)


@pytest.fixture
def recorded() -> list[httpx.Request]:
    return []


async def test_spot_balances_are_parsed_as_exact_decimals(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, httpx.Response(200, json=SPOT_PAYLOAD), recorded)

    balances = await client.spot_balances()

    assert [balance.coin for balance in balances] == ["USDT", "BTC"]
    assert balances[0].free == Decimal("12345.67891234")
    assert balances[0].frozen == Decimal("0.00000001")
    assert balances[0].debts is None


async def test_the_spot_read_is_signed_and_hits_the_spot_base_path(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, httpx.Response(200, json=SPOT_PAYLOAD), recorded)

    await client.spot_balances()

    request = recorded[0]
    assert request.method == "GET"
    assert request.url.path == SPOT_BALANCES_PATH
    assert request.url.params["timestamp"].isdigit()
    assert request.headers[KEY_HEADER] == "test-key-abcd"
    assert len(request.headers[SIGNATURE_HEADER]) == 64


async def test_the_transmitted_query_is_byte_identical_to_the_signed_one(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """If httpx re-encodes the query, the signature stops matching and every
    live call fails with an opaque authentication error."""
    signed = signer.sign("GET", SPOT_BALANCES_PATH)
    client = _client(signer, httpx.Response(200, json=SPOT_PAYLOAD), recorded)

    await client.spot_balances()

    sent = recorded[0].url
    assert f"{sent.path}?{sent.query.decode()}" == signed.path_with_query


async def test_futures_balances_use_the_uapi_path_and_expose_debts(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, httpx.Response(200, json=FUTURES_PAYLOAD), recorded)

    balances = await client.futures_balances()

    assert recorded[0].url.path == FUTURES_BALANCES_PATH
    assert FUTURES_BALANCES_PATH != SPOT_BALANCES_PATH
    assert balances[0].debts == Decimal("0.00000000")


async def test_a_rejected_result_becomes_a_pionex_api_error(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    payload = {"result": False, "code": "AUTH_FAILED", "message": "bad signature"}
    client = _client(signer, httpx.Response(200, json=payload), recorded)

    with pytest.raises(PionexApiError, match="bad signature") as caught:
        await client.spot_balances()

    assert caught.value.code == "AUTH_FAILED"


async def test_a_non_200_status_becomes_a_pionex_api_error(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, httpx.Response(401, text="unauthorized"), recorded)

    with pytest.raises(PionexApiError) as caught:
        await client.spot_balances()

    assert caught.value.http_status == 401


async def test_a_numeric_amount_is_rejected_rather_than_silently_coerced(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    """A JSON number has already lost precision before it reaches us. Better a
    loud failure than a balance that is quietly wrong in the eighth decimal."""
    payload = {
        "result": True,
        "data": {"balances": [{"coin": "USDT", "free": 12345.67891234, "frozen": "0"}]},
    }
    client = _client(signer, httpx.Response(200, json=payload), recorded)

    with pytest.raises(PionexApiError, match="must be a string amount"):
        await client.spot_balances()


async def test_a_malformed_envelope_becomes_a_pionex_api_error(
    signer: PionexSigner, recorded: list[httpx.Request]
) -> None:
    client = _client(signer, httpx.Response(200, json={"result": True}), recorded)

    with pytest.raises(PionexApiError, match="no data object"):
        await client.spot_balances()


def test_the_client_exposes_no_writing_method() -> None:
    """The read-only guarantee is structural. This test is the tripwire that
    fires the day someone adds order submission to the balance reader."""
    forbidden = ("order", "submit", "cancel", "close", "buy", "sell", "transfer",
                 "withdraw", "post", "delete", "put")
    public = [name for name in dir(PionexReadOnlyClient) if not name.startswith("_")]

    assert [name for name in public if any(word in name.lower() for word in forbidden)] == []

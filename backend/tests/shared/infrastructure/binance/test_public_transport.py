"""The credential-free Binance transport.

Binance reports failure through the status line, and answers HTTP 451 for a
location it excludes. The public transport must read both exactly as the signed
one does, because the catalogue is fetched from a server whose location is the
very thing that decides whether the answer is data.
"""

import inspect
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.signer import (
    KEY_HEADER,
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.binance.transport import (
    BinancePublicTransport,
    BinanceTransport,
)

EXCHANGE_INFO = "/fapi/v1/exchangeInfo"


class _Clock:
    def now(self) -> Any:
        raise AssertionError("a public read must never ask the clock to sign")


def _http(
    handler: Any, recorded: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    def record_and_answer(request: httpx.Request) -> httpx.Response:
        if recorded is not None:
            recorded.append(request)
        return handler(request)  # type: ignore[no-any-return]

    return httpx.AsyncClient(
        base_url="https://fapi.binance.com",
        transport=httpx.MockTransport(record_and_answer),
    )


async def test_public_get_refuses_a_negative_code_and_http_451_like_the_signed_transport() -> (
    None
):
    rejected = BinancePublicTransport(
        _http(lambda _: httpx.Response(200, json={"code": -1121, "msg": "Invalid symbol."}))
    )
    with pytest.raises(BinanceApiError, match="Invalid symbol") as negative:
        await rejected.get(EXCHANGE_INFO)
    assert negative.value.code == "-1121"

    refused = BinancePublicTransport(
        _http(lambda _: httpx.Response(451, json={"msg": "Service unavailable"}))
    )
    with pytest.raises(BinanceApiError, match="HTTP 451") as location:
        await refused.get(EXCHANGE_INFO)
    assert location.value.http_status == 451

    # The signed transport reads the same two answers the same way.
    signer = BinanceSigner(BinanceCredentials("key-abcd", "secret"), _Clock())
    signed = BinanceTransport(
        _http(lambda _: httpx.Response(451, json={"msg": "Service unavailable"})), signer
    )
    with pytest.raises(BinanceApiError, match="HTTP 451"):
        await signed.get_public(EXCHANGE_INFO)


async def test_public_get_returns_the_payload_unchanged() -> None:
    transport = BinancePublicTransport(
        _http(lambda _: httpx.Response(200, json={"symbols": [{"symbol": "AAVEUSDT"}]}))
    )

    payload = await transport.get(EXCHANGE_INFO)

    assert payload == {"symbols": [{"symbol": "AAVEUSDT"}]}


async def test_public_get_sends_no_api_key_header_and_no_signature_parameter() -> None:
    recorded: list[httpx.Request] = []
    transport = BinancePublicTransport(
        _http(lambda _: httpx.Response(200, json={"symbols": []}), recorded)
    )

    await transport.get(EXCHANGE_INFO, {"symbol": "AAVEUSDT"})

    assert len(recorded) == 1
    request = recorded[0]
    assert KEY_HEADER not in request.headers
    assert [n for n in request.headers if n.lower().startswith("x-mbx")] == []
    assert "signature" not in request.url.params
    assert "timestamp" not in request.url.params
    assert dict(request.url.params) == {"symbol": "AAVEUSDT"}
    assert request.url.path == EXCHANGE_INFO


def test_public_transport_constructor_takes_no_signer() -> None:
    parameters = inspect.signature(BinancePublicTransport.__init__).parameters

    assert list(parameters) == ["self", "http"]


async def test_binance_transport_get_public_answers_through_the_public_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, dict[str, str] | None]] = []

    async def fake_get(
        self: BinancePublicTransport, path: str, params: Any = None
    ) -> Any:
        seen.append((path, None if params is None else dict(params)))
        return {"via": "public transport"}

    monkeypatch.setattr(BinancePublicTransport, "get", fake_get)
    signer = BinanceSigner(BinanceCredentials("key-abcd", "secret"), _Clock())
    transport = BinanceTransport(
        _http(lambda _: httpx.Response(200, json={"via": "its own send"})), signer
    )

    answer = await transport.get_public(EXCHANGE_INFO, {"symbol": "AAVEUSDT"})

    assert answer == {"via": "public transport"}
    assert seen == [(EXCHANGE_INFO, {"symbol": "AAVEUSDT"})]

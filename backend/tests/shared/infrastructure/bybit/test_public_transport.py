"""The credential-free Bybit transport.

It exists so the API process can read Bybit's public catalogue without a vault
row, a signer or a key. Everything about "cannot sign" is pinned here: by the
constructor's type, and by what actually goes out on the wire.
"""

import inspect
from typing import Any

import httpx
import pytest

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.transport import (
    BybitPublicTransport,
)

INSTRUMENTS = "/v5/market/instruments-info"


def _transport(
    handler: Any, recorded: list[httpx.Request] | None = None
) -> BybitPublicTransport:
    def record_and_answer(request: httpx.Request) -> httpx.Response:
        if recorded is not None:
            recorded.append(request)
        return handler(request)  # type: ignore[no-any-return]

    http = httpx.AsyncClient(
        base_url="https://api.bybit.com",
        transport=httpx.MockTransport(record_and_answer),
    )
    return BybitPublicTransport(http)


async def test_public_get_refuses_a_nonzero_retcode_over_http_200() -> None:
    """Bybit reports a business failure over HTTP 200. Reading the status line
    alone would hand the caller a rejection as if it were data."""
    transport = _transport(
        lambda _: httpx.Response(
            200, json={"retCode": 10001, "retMsg": "params error", "result": {}}
        )
    )

    with pytest.raises(BybitApiError, match="params error") as raised:
        await transport.get(INSTRUMENTS, {"category": "linear"})

    assert raised.value.code == "10001"


async def test_public_get_returns_the_result_object_not_the_envelope() -> None:
    transport = _transport(
        lambda _: httpx.Response(
            200,
            json={"retCode": 0, "retMsg": "OK", "result": {"list": [], "marker": 7}},
        )
    )

    result = await transport.get(INSTRUMENTS)

    assert result == {"list": [], "marker": 7}


async def test_public_get_sends_no_bapi_header() -> None:
    """Pinned on the outgoing request, not on the class: no ``X-BAPI-*``
    header of any kind, and no ``signature`` or ``timestamp`` parameter."""
    recorded: list[httpx.Request] = []
    transport = _transport(
        lambda _: httpx.Response(200, json={"retCode": 0, "result": {}}), recorded
    )

    await transport.get(INSTRUMENTS, {"category": "linear", "limit": "1000"})

    assert len(recorded) == 1
    request = recorded[0]
    assert [n for n in request.headers if n.lower().startswith("x-bapi")] == []
    assert "signature" not in request.url.params
    assert "timestamp" not in request.url.params
    assert dict(request.url.params) == {"category": "linear", "limit": "1000"}
    assert request.url.path == INSTRUMENTS


def test_public_transport_constructor_takes_no_signer() -> None:
    parameters = inspect.signature(BybitPublicTransport.__init__).parameters

    assert list(parameters) == ["self", "http"]

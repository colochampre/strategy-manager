"""HTTP transport for Binance's REST API.

**Binance reports failures through the status line**, unlike Pionex and Bybit,
which answer a rejection with HTTP 200 and an error code inside the body. Here
a rejection is a 4xx carrying ``{"code": <negative>, "msg": ...}``. A 200 is
read as success, but a 200 body that still carries a negative ``code`` is
refused too, because treating it as data is how a rejection gets recorded as
an answer.

A signed POST carries its parameters in an ``application/x-www-form-urlencoded``
body rather than JSON, which is the shape Binance signs; the signer produces
that string and this sends those exact bytes.

HTTP 451 gets its own message. Binance returns it for requests from a location
its terms exclude, and it is a property of where the request comes from, not
of the key or the request -- retrying or re-signing changes nothing.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import httpx

from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.signer import BinanceSigner

_RESTRICTED_LOCATION = 451

# Binance takes a signed POST's parameters as a form-encoded body, not as JSON.
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


class BinanceTransport:
    """Sends public or signed requests to one Binance host."""

    def __init__(self, http: httpx.AsyncClient, signer: BinanceSigner) -> None:
        self._http = http
        self._signer = signer

    async def get_public(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        return await BinancePublicTransport(self._http).get(path, params)

    async def get_signed(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        signed = self._signer.sign_get(path, params)
        return await send_request(
            "GET",
            path,
            lambda: self._http.get(signed.path_with_query, headers=dict(signed.headers)),
        )

    async def post(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        """A signed POST. The parameters are sent as the exact signed body.

        Routed through the same ``send_request`` as the GETs on purpose: the
        451 answer and the negative-``code`` rejection must be read
        identically however the request was shaped, because a rejection only
        some verbs recognise is a rejection that gets recorded as an answer.
        """
        signed = self._signer.sign_post(path, params)
        headers = {**signed.headers, "Content-Type": FORM_CONTENT_TYPE}
        return await send_request(
            "POST",
            path,
            lambda: self._http.post(
                signed.path_with_query,
                headers=headers,
                content=signed.body.encode("utf-8"),
            ),
        )


class BinancePublicTransport:
    """Reads Binance's public market data. It cannot sign.

    The constructor takes an HTTP client and nothing else, so a process that
    builds only this class has no signer, no credential and no API-key header.
    A 451, a non-JSON body and a negative ``code`` are read by the same
    function the signed transport uses.
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        query = urlencode(dict(params or {}))
        return await send_request(
            "GET", path, lambda: self._http.get(f"{path}?{query}" if query else path)
        )


async def send_request(
    method: str,
    path: str,
    call: Callable[[], Awaitable[httpx.Response]],
) -> Any:
    """Runs one request and applies Binance's failure reading to the answer.

    A module-level function, not a method, so that every transport in this
    file reads a 451, a non-JSON body and a negative ``code`` identically
    whether or not the request was signed.
    """
    try:
        response = await call()
    except httpx.HTTPError as exc:
        raise BinanceApiError(f"{method} {path} failed: {exc}") from exc

    if response.status_code == _RESTRICTED_LOCATION:
        raise BinanceApiError(
            f"{method} {path} returned HTTP 451: Binance refuses requests from "
            "this location. It depends on where the request comes from, not on "
            "the key or the request.",
            http_status=_RESTRICTED_LOCATION,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise BinanceApiError(
            f"{method} {path} returned HTTP {response.status_code} with a non-JSON body",
            http_status=response.status_code,
        ) from exc

    code = payload.get("code") if isinstance(payload, dict) else None
    rejected = isinstance(code, int) and code < 0
    if response.status_code != httpx.codes.OK or rejected:
        message = payload.get("msg") if isinstance(payload, dict) else None
        raise BinanceApiError(
            str(message or f"{method} {path} returned HTTP {response.status_code}"),
            code=None if code is None else str(code),
            http_status=response.status_code,
        )

    return payload

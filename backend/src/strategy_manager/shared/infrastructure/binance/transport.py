"""HTTP transport for Binance's REST API.

**Binance reports failures through the status line**, unlike Pionex and Bybit,
which answer a rejection with HTTP 200 and an error code inside the body. Here
a rejection is a 4xx carrying ``{"code": <negative>, "msg": ...}``. A 200 is
read as success, but a 200 body that still carries a negative ``code`` is
refused too, because treating it as data is how a rejection gets recorded as
an answer.

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


class BinanceTransport:
    """Sends public or signed GETs to one Binance host."""

    def __init__(self, http: httpx.AsyncClient, signer: BinanceSigner) -> None:
        self._http = http
        self._signer = signer

    async def get_public(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        query = urlencode(dict(params or {}))
        return await self._send(
            "GET", path, lambda: self._http.get(f"{path}?{query}" if query else path)
        )

    async def get_signed(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        signed = self._signer.sign_get(path, params)
        return await self._send(
            "GET",
            path,
            lambda: self._http.get(signed.path_with_query, headers=dict(signed.headers)),
        )

    async def _send(
        self,
        method: str,
        path: str,
        call: Callable[[], Awaitable[httpx.Response]],
    ) -> Any:
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

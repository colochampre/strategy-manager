"""Signed HTTP transport for the Pionex REST API.

Everything every Pionex call shares and nothing any of them differs by:
sign, send the exact signed bytes, unwrap the ``{"result": ..., "data": ...}``
envelope, and turn every failure into ``PionexApiError``. What the ``data``
payload means is the caller's business.

The two methods differ in exactly one way that matters. A GET signs its query
and sends no body. A POST signs the JSON body verbatim and sends *that same
string*, never a re-serialized dict -- ``httpx``'s ``json=`` argument would
produce ``{"symbol": "BTC_USDT"}`` where the signature was computed over
``{"symbol":"BTC_USDT"}``, and Pionex would reject it with an authentication
error that says nothing about whitespace.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from strategy_manager.shared.infrastructure.pionex.errors import PionexApiError
from strategy_manager.shared.infrastructure.pionex.signer import PionexSigner

JSON_CONTENT_TYPE = "application/json"


class PionexTransport:
    """Signs, sends and unwraps. Holds no opinion about any endpoint."""

    def __init__(self, http: httpx.AsyncClient, signer: PionexSigner) -> None:
        self._http = http
        self._signer = signer

    async def get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        signed = self._signer.sign("GET", path, params)
        return await self._send(
            "GET",
            path,
            lambda: self._http.get(
                signed.path_with_query, headers=dict(signed.headers)
            ),
        )

    async def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        """``payload`` is serialized exactly once, here.

        The compact separators are not cosmetic: the body is signed and sent
        as one immutable string, so the serialization must happen before the
        signature and never again after it.
        """
        body = json.dumps(payload, separators=(",", ":"))
        signed = self._signer.sign("POST", path, body=body)
        headers = {**signed.headers, "Content-Type": JSON_CONTENT_TYPE}
        return await self._send(
            "POST",
            path,
            lambda: self._http.post(
                signed.path_with_query,
                headers=headers,
                content=signed.body.encode("utf-8"),
            ),
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
            raise PionexApiError(f"{method} {path} failed: {exc}") from exc

        if response.status_code != httpx.codes.OK:
            raise PionexApiError(
                f"{method} {path} returned HTTP {response.status_code}",
                http_status=response.status_code,
            )

        try:
            envelope = response.json()
        except ValueError as exc:
            raise PionexApiError(f"{method} {path} returned a non-JSON body") from exc

        if not isinstance(envelope, dict):
            raise PionexApiError(f"{method} {path} returned a non-object body")

        if envelope.get("result") is not True:
            code = envelope.get("code")
            raise PionexApiError(
                str(
                    envelope.get("message")
                    or f"{method} {path} was rejected by Pionex"
                ),
                code=None if code is None else str(code),
            )

        # The envelope's ``result`` semantics are this class's business; the
        # shape of ``data`` is the caller's, because every endpoint returns a
        # different one and only the caller knows which it asked for.
        return envelope.get("data")

"""Signed HTTP transport for the Bybit V5 REST API.

Everything every Bybit call shares and nothing any of them differs by: sign,
send the exact signed bytes, unwrap the ``{"retCode": ..., "retMsg": ...,
"result": ...}`` envelope, and turn every failure into ``BybitApiError``.
What the ``result`` payload means is the caller's business.

**Bybit reports business failures over HTTP 200**, exactly as Pionex does: a
rejected order comes back with a 200 status and a non-zero ``retCode`` in the
body. Reading the status line alone would treat every rejection as a success,
which is how an order that never existed gets recorded as placed. The envelope
is the contract; the status line is not.

``retCode: 0`` is success. Everything else carries a code, and that code is
what the execution layer uses to decide whether a failure is definitive — the
exchange saw the order and refused it — or unknown, where the only safe move
is to ask again rather than release the capital behind it.
"""

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx

from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.signer import BybitSigner

JSON_CONTENT_TYPE = "application/json"

SUCCESS_CODE = 0


class BybitTransport:
    """Signs, sends and unwraps. Holds no opinion about any endpoint."""

    def __init__(self, http: httpx.AsyncClient, signer: BybitSigner) -> None:
        self._http = http
        self._signer = signer

    async def get(self, path: str, params: Mapping[str, str] | None = None) -> Any:
        signed = self._signer.sign_get(path, params)
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
        signed = self._signer.sign_post(path, body)
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
            raise BybitApiError(f"{method} {path} failed: {exc}") from exc

        if response.status_code != httpx.codes.OK:
            raise BybitApiError(
                f"{method} {path} returned HTTP {response.status_code}",
                http_status=response.status_code,
            )

        try:
            envelope = response.json()
        except ValueError as exc:
            raise BybitApiError(f"{method} {path} returned a non-JSON body") from exc

        if not isinstance(envelope, dict):
            raise BybitApiError(f"{method} {path} returned a non-object body")

        code = envelope.get("retCode")
        if code != SUCCESS_CODE:
            raise BybitApiError(
                str(envelope.get("retMsg") or f"{method} {path} was rejected by Bybit"),
                code=None if code is None else str(code),
            )

        return envelope.get("result")

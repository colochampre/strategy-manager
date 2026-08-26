"""Request signing for the Bybit V5 REST API.

Pure computation plus an injected clock: no HTTP, no persistence, no I/O.

The signing contract is Bybit's own, from the V5 guide:

    GET   sign over  timestamp + api_key + recv_window + queryString
    POST  sign over  timestamp + api_key + recv_window + rawJsonBody

HMAC-SHA256 with the API secret, lowercase hex, sent as ``X-BAPI-SIGN``
alongside ``X-BAPI-API-KEY``, ``X-BAPI-TIMESTAMP`` and ``X-BAPI-RECV-WINDOW``.

**Where this goes wrong is the same place it went wrong on Pionex**, and it is
worth stating rather than rediscovering: the signature is computed over one
byte sequence and a convenience API transmits a different one.

- A GET's query string is signed as written. An HTTP client handed a
  parameter mapping may reorder or percent-encode it, and the signature no
  longer matches what was sent.
- A POST body is signed as a string. An HTTP client handed a dict re-serializes
  it with its own separators and key order, so a body signed as
  ``{"category":"linear"}`` goes out as ``{"category": "linear"}`` — one
  space, and authentication fails with an error that says nothing about
  whitespace.

``SignedRequest`` closes both gaps the way the Pionex one does: it carries the
exact query string AND the exact body that were signed, so the caller
transmits those bytes rather than rebuilding either.

Unlike Pionex, Bybit puts none of the authentication in the query, so the
query is only the endpoint's own parameters. Their ORDER still matters,
because it is the order that was signed — which is why this takes an ordered
mapping and never sorts it behind the caller's back.
"""

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlencode

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation

KEY_HEADER = "X-BAPI-API-KEY"
SIGNATURE_HEADER = "X-BAPI-SIGN"
TIMESTAMP_HEADER = "X-BAPI-TIMESTAMP"
RECV_WINDOW_HEADER = "X-BAPI-RECV-WINDOW"


@dataclass(frozen=True, slots=True, repr=False)
class BybitCredentials:
    """An API key pair, held in memory only for as long as it takes to sign."""

    api_key: str
    api_secret: str

    def __post_init__(self) -> None:
        if not self.api_key:
            raise InvariantViolation("BybitCredentials.api_key must not be empty")
        if not self.api_secret:
            raise InvariantViolation("BybitCredentials.api_secret must not be empty")

    def __repr__(self) -> str:
        """Redacted on purpose: a default dataclass repr puts the secret into
        every log line and traceback that touches this object. A last-4 hint
        is the most that may ever be rendered (CLAUDE.md rule 8).
        """
        return f"BybitCredentials(api_key='***{self.api_key[-4:]}', api_secret='***')"


@dataclass(frozen=True, slots=True)
class SignedRequest:
    """Exactly what to put on the wire.

    ``path_with_query`` and ``body`` are the signed byte sequences: send them
    as-is.
    """

    path_with_query: str
    headers: Mapping[str, str]
    body: str = ""


class BybitSigner:
    """Signs requests for the Bybit V5 REST API."""

    def __init__(
        self,
        credentials: BybitCredentials,
        clock: ClockPort,
        recv_window_ms: int = 5000,
    ) -> None:
        if recv_window_ms <= 0:
            raise InvariantViolation("recv_window_ms must be positive")
        self._credentials = credentials
        self._clock = clock
        self._recv_window = str(recv_window_ms)

    def sign_get(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> SignedRequest:
        query = urlencode(dict(params or {}))
        return SignedRequest(
            path_with_query=f"{path}?{query}" if query else path,
            headers=self._headers(query),
        )

    def sign_post(self, path: str, body: str) -> SignedRequest:
        """``body`` is already serialized. It is signed and sent as the same
        string, because re-serializing it would change the bytes."""
        return SignedRequest(
            path_with_query=path,
            headers=self._headers(body),
            body=body,
        )

    def _headers(self, payload: str) -> Mapping[str, str]:
        """The timestamp is read once and used for both the signature and the
        header.

        Deliberately not stored on the instance: a signature signed with one
        timestamp and sent with another is rejected, and holding it as
        mutable state would make that failure depend on call order. One
        signer can then serve concurrent requests, which the per-job clients
        do.
        """
        timestamp = str(self._timestamp_ms())
        message = (
            f"{timestamp}{self._credentials.api_key}{self._recv_window}{payload}"
        )
        signature = hmac.new(
            self._credentials.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            sha256,
        ).hexdigest()

        return {
            KEY_HEADER: self._credentials.api_key,
            SIGNATURE_HEADER: signature,
            TIMESTAMP_HEADER: timestamp,
            RECV_WINDOW_HEADER: self._recv_window,
        }

    def _timestamp_ms(self) -> int:
        """Bybit requires ``server_time - recv_window <= timestamp <
        server_time + 1000``, so this reads the injected ``ClockPort`` rather
        than the wall clock — the same discipline the Pionex signer uses, and
        the reason both are testable without freezing real time.
        """
        return int(self._clock.now().timestamp() * 1000)

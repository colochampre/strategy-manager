"""Request signing for Binance's SIGNED REST endpoints.

Pure computation plus an injected clock: no HTTP, no persistence, no I/O.

Binance's contract, from its request-security documentation:

    signature = HMAC-SHA256(secret, query_string + body), lowercase hex

``timestamp`` (milliseconds) and the optional ``recvWindow`` travel as ordinary
query parameters, the signature is appended as the last parameter
``signature``, and the key goes in the ``X-MBX-APIKEY`` header. Binance rejects
a request whose ``timestamp`` is 1000 ms or more ahead of its clock, or older
than ``recvWindow``.

The failure mode is the one the Pionex and Bybit signers already name: the
signature covers one byte sequence and a convenience API sends another. So the
query string is built once, signed as built, and transmitted exactly as signed
-- ``SignedRequest.path_with_query`` is those bytes.
"""

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlencode

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation

KEY_HEADER = "X-MBX-APIKEY"
SIGNATURE_PARAM = "signature"

# Binance's documented ceiling for recvWindow.
MAX_RECV_WINDOW_MS = 60_000


@dataclass(frozen=True, slots=True, repr=False)
class BinanceCredentials:
    """An API key pair, held in memory only for as long as it takes to sign."""

    api_key: str
    api_secret: str

    def __post_init__(self) -> None:
        if not self.api_key:
            raise InvariantViolation("BinanceCredentials.api_key must not be empty")
        if not self.api_secret:
            raise InvariantViolation("BinanceCredentials.api_secret must not be empty")

    def __repr__(self) -> str:
        """Redacted: a last-4 hint is the most that may ever be rendered
        (CLAUDE.md rule 8)."""
        return f"BinanceCredentials(api_key='***{self.api_key[-4:]}', api_secret='***')"


def signature_for(secret: str, payload: str) -> str:
    """HMAC-SHA256 of ``payload`` under ``secret``, as lowercase hex."""
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class SignedRequest:
    """Exactly what to put on the wire. Send ``path_with_query`` as-is."""

    path_with_query: str
    headers: Mapping[str, str]


class BinanceSigner:
    """Signs GET requests for Binance's SIGNED endpoints."""

    def __init__(
        self,
        credentials: BinanceCredentials,
        clock: ClockPort,
        recv_window_ms: int = 5000,
    ) -> None:
        if not 0 < recv_window_ms <= MAX_RECV_WINDOW_MS:
            raise InvariantViolation(
                f"recv_window_ms must be in (0, {MAX_RECV_WINDOW_MS}], got {recv_window_ms}"
            )
        self._credentials = credentials
        self._clock = clock
        self._recv_window = str(recv_window_ms)

    def sign_get(self, path: str, params: Mapping[str, str] | None = None) -> SignedRequest:
        """The endpoint's own parameters keep the caller's order; ``recvWindow``
        and ``timestamp`` follow, and ``signature`` is appended last over
        everything before it."""
        query = urlencode(
            [
                *dict(params or {}).items(),
                ("recvWindow", self._recv_window),
                ("timestamp", str(self._timestamp_ms())),
            ]
        )
        signature = signature_for(self._credentials.api_secret, query)
        return SignedRequest(
            path_with_query=f"{path}?{query}&{SIGNATURE_PARAM}={signature}",
            headers={KEY_HEADER: self._credentials.api_key},
        )

    def _timestamp_ms(self) -> int:
        return int(self._clock.now().timestamp() * 1000)

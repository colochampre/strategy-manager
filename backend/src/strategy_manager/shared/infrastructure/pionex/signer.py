"""Request signing for the Pionex REST API.

Pure computation plus an injected clock: no HTTP, no persistence, no I/O.

The signing contract is Pionex's own, verified 2026-08-20 against
https://pionex-doc.gitbook.io/apidocs/restful/general/authentication:

1. Collect the query parameters and add ``timestamp`` in milliseconds.
2. Sort them in ascending ASCII order by key and join them with ``&``.
   Values are signed RAW -- Pionex does not URL-encode them.
3. The signed payload is ``METHOD + path + "?" + query``, plus the request
   body verbatim for POST/DELETE. A GET has no body, so that part is empty.
4. HMAC-SHA256 that payload with the API secret; take lowercase hex.
5. Send the API key as ``PIONEX-KEY`` and the hex digest as
   ``PIONEX-SIGNATURE``.

Steps 2 and 3 are where this silently goes wrong, in the same way and for
the same reason: the signature is computed over one byte sequence and a
convenience API transmits a different one. An HTTP client building a URL from
a parameter mapping percent-encodes the values the signature was computed
over raw. An HTTP client handed a ``json=`` dict re-serializes it with its
own separator and key-order choices, so a body signed as
``{"symbol":"BTC_USDT"}`` goes out as ``{"symbol": "BTC_USDT"}`` -- one space,
and authentication fails with no useful error.

``SignedRequest`` closes both gaps the same way: it carries the exact query
string AND the exact body that were signed, so the caller transmits those
bytes verbatim rather than rebuilding either. Any parameter value that is not
already URL-safe is rejected up front instead of producing a signature that
cannot match.
"""

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation

KEY_HEADER = "PIONEX-KEY"
SIGNATURE_HEADER = "PIONEX-SIGNATURE"

TIMESTAMP_PARAM = "timestamp"

# RFC 3986 unreserved characters. A parameter built only from these survives
# URL encoding unchanged, so the signed query and the sent query stay equal.
_URL_SAFE = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


@dataclass(frozen=True, slots=True, repr=False)
class PionexCredentials:
    """An API key pair, held in memory only for as long as it takes to sign."""

    api_key: str
    api_secret: str

    def __post_init__(self) -> None:
        if not self.api_key:
            raise InvariantViolation("PionexCredentials.api_key must not be empty")
        if not self.api_secret:
            raise InvariantViolation("PionexCredentials.api_secret must not be empty")

    def __repr__(self) -> str:
        """Redacted on purpose: a default dataclass repr puts the secret into
        every log line and traceback that touches this object. A last-4 hint
        is the most that may ever be rendered (CLAUDE.md rule 8).
        """
        return f"PionexCredentials(api_key='***{self.api_key[-4:]}', api_secret='***')"


@dataclass(frozen=True, slots=True)
class SignedRequest:
    """Exactly what to put on the wire.

    ``path_with_query`` and ``body`` are the signed byte sequences: send them
    as-is. Rebuilding the query from a parameter mapping, or the body from a
    dict, invalidates the signature.
    """

    path_with_query: str
    headers: Mapping[str, str]
    body: str = ""


class PionexSigner:
    """Signs requests for the Pionex REST API."""

    def __init__(self, credentials: PionexCredentials, clock: ClockPort) -> None:
        self._credentials = credentials
        self._clock = clock

    def sign(
        self,
        method: str,
        path: str,
        params: Mapping[str, str] | None = None,
        body: str = "",
    ) -> SignedRequest:
        signed_params = dict(params or {})
        if TIMESTAMP_PARAM in signed_params:
            raise InvariantViolation(
                "timestamp is supplied by the signer, not by the caller"
            )
        signed_params[TIMESTAMP_PARAM] = str(self._timestamp_ms())

        for key, value in signed_params.items():
            _assert_url_safe("key", key)
            _assert_url_safe("value", value)

        query = "&".join(f"{key}={signed_params[key]}" for key in sorted(signed_params))
        path_with_query = f"{path}?{query}"
        payload = f"{method.upper()}{path_with_query}{body}"

        signature = hmac.new(
            self._credentials.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            sha256,
        ).hexdigest()

        return SignedRequest(
            path_with_query=path_with_query,
            headers={
                KEY_HEADER: self._credentials.api_key,
                SIGNATURE_HEADER: signature,
            },
            body=body,
        )

    def _timestamp_ms(self) -> int:
        """Pionex rejects a timestamp more than 20 seconds from its own clock,
        so this reads the injected ``ClockPort`` rather than the wall clock.
        """
        return int(self._clock.now().timestamp() * 1000)


def _assert_url_safe(part: str, text: str) -> None:
    if not text or not set(text) <= _URL_SAFE:
        raise InvariantViolation(
            f"query parameter {part} {text!r} is not URL-safe; Pionex signs raw "
            "values, so a character needing encoding would break the signature"
        )

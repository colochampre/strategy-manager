"""Asks Binance whether a candidate key can be used, and nothing more.

One GET: ``GET /fapi/v3/account``. It is rule 8a, the live read. It proves the
key authenticates from this host and can read; it proves NOTHING about
trading or withdrawing (probe P6: a key without "Enable Futures" reads every
fapi endpoint).

So this inspector returns an EMPTY snapshot on purpose. Binance's trade and
withdraw facts are owner-confirmed (decisions 24 and 30). Two things it must
never do:

- read the account-level ``canTrade`` / ``canWithdraw`` flags for any purpose:
  P6 found both true on a key that could neither trade futures nor withdraw,
  and reading them would record a false "verified";
- call SAPI (``apiRestrictions``): it answers 403 from the VPS (P3).

GET-only by construction: it calls ``get_signed`` on the transport and imports
nothing from ``trade_client``.
"""

from typing import Final

import httpx

from strategy_manager.accounts.domain.errors import KeyRejected, VenueUnreachable
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.key_policy import PermissionSnapshot
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.binance.errors import BinanceApiError
from strategy_manager.shared.infrastructure.binance.read_client import ACCOUNT_PATH
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.binance.transport import BinanceTransport

# -2014 API-key format invalid, -2015 invalid key / IP / permissions,
# -1022 signature invalid.
_AUTH_CODES: Final = frozenset({"-2014", "-2015", "-1022"})
_AMBIGUOUS_REJECTION: Final = "-2015"


class BinanceKeyInspector:
    """Implements ``KeyInspectorPort`` for Binance USDⓈ-M futures."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        recv_window_ms: int,
        clock: ClockPort,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._recv_window_ms = recv_window_ms
        self._clock = clock
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings, clock: ClockPort) -> "BinanceKeyInspector":
        return cls(
            base_url=settings.binance_futures_base_url,
            timeout_seconds=settings.binance_timeout_seconds,
            recv_window_ms=settings.binance_recv_window_ms,
            clock=clock,
        )

    async def inspect(self, credential: ExchangeCredential) -> PermissionSnapshot:
        signer = BinanceSigner(
            BinanceCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            self._clock,
            recv_window_ms=self._recv_window_ms,
        )
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=self._transport
        ) as http:
            try:
                payload = await BinanceTransport(http, signer).get_signed(ACCOUNT_PATH)
            except BinanceApiError as exc:
                # ``from None``: a signed Binance query carries its signature
                # in the URL, and the wrapped text may quote the request.
                raise _translate(exc) from None

        if not isinstance(payload, dict):
            raise VenueUnreachable("binance answered the account read with a non-object body")
        # The body is deliberately not read any further.
        return PermissionSnapshot()


def _translate(exc: BinanceApiError) -> KeyRejected | VenueUnreachable:
    if exc.code in _AUTH_CODES:
        if exc.code == _AMBIGUOUS_REJECTION:
            return KeyRejected(
                "binance rejected the key (code -2015): -2015 also covers a source IP "
                "that is not allowlisted and a missing permission, not only a bad key"
            )
        return KeyRejected(f"binance rejected the key (code {exc.code})")
    if exc.http_status is not None:
        return VenueUnreachable(f"binance could not be read (HTTP {exc.http_status})")
    return VenueUnreachable("binance could not be read (transport failure)")

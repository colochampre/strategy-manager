"""Asks Bybit what a candidate key is allowed to do.

Two GETs, in this order:

1. ``GET /v5/account/wallet-balance`` -- rule 8a, the live read. A key the
   venue refuses fails here (``KeyRejected``) and nothing else is asked.
2. ``GET /v5/user/query-api`` -- ``permissions.Wallet`` and ``readOnly``, the
   two facts Bybit can prove (probes P1 and P2).

**Fail-closed.** A missing or non-list ``Wallet``, or a ``readOnly`` that is not
exactly 0 or 1, comes back as ``None`` in the snapshot, and ``evaluate_key``
turns that into ``PERMISSIONS_UNAVAILABLE``. It is never read as "no
withdrawal" or "can trade". The inspector logs one WARNING naming the exchange
and WHICH field was unusable, never the payload: that payload carries the
owner's whitelisted IPs and user id.

The permission lists other than ``Wallet`` (``ContractTrade``, ``Derivatives``)
are not read. A read-only key still lists them, so they say nothing about
trade capability.

GET-only by construction: this module builds a ``BybitReadOnlyClient``, which
has no method that writes, and imports nothing from ``trade_client``.
"""

import logging
from collections.abc import Mapping
from typing import Any, Final

import httpx

from strategy_manager.accounts.domain.errors import KeyRejected, VenueUnreachable
from strategy_manager.accounts.domain.exchange_credential import ExchangeCredential
from strategy_manager.accounts.domain.key_policy import PermissionSnapshot
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.bybit import EXCHANGE
from strategy_manager.shared.infrastructure.bybit.errors import BybitApiError
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient
from strategy_manager.shared.infrastructure.bybit.signer import BybitCredentials, BybitSigner

logger = logging.getLogger(__name__)

# retCode 10003 invalid api key, 10004 invalid sign, 33004 api key expired.
_AUTH_CODES: Final = frozenset({"10003", "10004", "33004"})


class BybitKeyInspector:
    """Implements ``KeyInspectorPort`` for Bybit."""

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
    def from_settings(cls, settings: Settings, clock: ClockPort) -> "BybitKeyInspector":
        return cls(
            base_url=settings.bybit_base_url,
            timeout_seconds=settings.bybit_timeout_seconds,
            recv_window_ms=settings.bybit_recv_window_ms,
            clock=clock,
        )

    async def inspect(self, credential: ExchangeCredential) -> PermissionSnapshot:
        signer = BybitSigner(
            BybitCredentials(api_key=credential.api_key, api_secret=credential.api_secret),
            self._clock,
            recv_window_ms=self._recv_window_ms,
        )
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds, transport=self._transport
        ) as http:
            client = BybitReadOnlyClient(http, signer)
            try:
                await client.unified_account_raw()
                info = await client.api_key_info()
            except BybitApiError as exc:
                # ``from None``: the wrapped text is the venue's or the
                # transport's, and none of it belongs in a traceback.
                raise _translate(exc) from None
        return _snapshot(info)


def _translate(exc: BybitApiError) -> KeyRejected | VenueUnreachable:
    if exc.code in _AUTH_CODES:
        return KeyRejected(f"bybit rejected the key (retCode {exc.code})")
    if exc.http_status is not None:
        return VenueUnreachable(f"bybit could not be read (HTTP {exc.http_status})")
    if exc.code is not None:
        return VenueUnreachable(f"bybit answered an unexpected retCode {exc.code}")
    return VenueUnreachable("bybit could not be read (transport failure or unexpected shape)")


def _snapshot(info: Mapping[str, Any]) -> PermissionSnapshot:
    wallet = _wallet_permissions(info.get("permissions"))
    read_only = _read_only(info.get("readOnly"))

    unusable = [
        name
        for name, value in (("permissions.Wallet", wallet), ("readOnly", read_only))
        if value is None
    ]
    if unusable:
        logger.warning(
            "%s key-info answer had no usable %s; the save will be refused as "
            "PERMISSIONS_UNAVAILABLE",
            EXCHANGE,
            " or ".join(unusable),
        )
    return PermissionSnapshot(wallet_permissions=wallet, read_only=read_only)


def _wallet_permissions(permissions: object) -> frozenset[str] | None:
    if not isinstance(permissions, Mapping):
        return None
    wallet = permissions.get("Wallet")
    if not isinstance(wallet, list) or not all(isinstance(token, str) for token in wallet):
        return None
    return frozenset(wallet)


def _read_only(value: object) -> bool | None:
    """Exactly the integers 0 and 1 (P2). A bool, a string or anything else is
    not what was probed, so it is not trusted."""
    if type(value) is int and value in (0, 1):
        return value == 1
    return None

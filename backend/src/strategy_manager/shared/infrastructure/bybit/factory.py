"""Builds configured Bybit clients.

Credentials are passed in rather than read here, for the reason the Pionex
factory gives: there are two legitimate sources and they are not
interchangeable. The worker loads them from the envelope-encrypted vault,
which is the system of record; a standalone probe reads them from the
environment, which is a developer convenience and never signs an order.

Keeping the choice at the call site means neither source can silently stand in
for the other — a lesson that already cost one wrong conclusion on the other
venue, where a write refused for using the read-only key looked exactly like a
write the venue forbade.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient
from strategy_manager.shared.infrastructure.bybit.signer import (
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import BybitTradeClient
from strategy_manager.shared.infrastructure.bybit.transport import BybitTransport
from strategy_manager.shared.infrastructure.clock import SystemClock


def credentials_from_settings(settings: Settings) -> BybitCredentials:
    """Reads the environment-configured key pair.

    Raises rather than letting an unauthenticated request reach Bybit and come
    back as an opaque signature failure.
    """
    if not settings.bybit_api_key or not settings.bybit_api_secret:
        raise InvariantViolation(
            "BYBIT_API_KEY and BYBIT_API_SECRET must be set to read Bybit "
            "account state from the environment"
        )
    return BybitCredentials(
        api_key=settings.bybit_api_key,
        api_secret=settings.bybit_api_secret,
    )


@asynccontextmanager
async def read_only_client(
    settings: Settings,
    credentials: BybitCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BybitReadOnlyClient]:
    """Yields a read-only client bound to the supplied credentials."""
    signer = _signer(settings, credentials, clock)

    async with _http(settings) as http:
        yield BybitReadOnlyClient(http, signer)


@asynccontextmanager
async def trade_client(
    settings: Settings,
    credentials: BybitCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BybitTradeClient]:
    """Yields a client that can place orders.

    Deliberately a separate entry point from ``read_only_client``. Anything
    that only reads should be unable to reach a writing client by accident,
    and a call site asking for this one is stating plainly that it intends to
    move money.
    """
    signer = _signer(settings, credentials, clock)

    async with _http(settings) as http:
        yield BybitTradeClient(http, signer)


@asynccontextmanager
async def signed_transport(
    settings: Settings,
    credentials: BybitCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BybitTransport]:
    """Yields the bare signed transport, for probes that need the raw envelope
    rather than a parsed read model.

    Public and deliberately narrow: a script asking "what exactly does Bybit
    answer here?" cannot use a typed client, because the whole point of asking
    is that the typed shape is not yet known to be right.
    """
    signer = _signer(settings, credentials, clock)

    async with _http(settings) as http:
        yield BybitTransport(http, signer)


def _signer(
    settings: Settings, credentials: BybitCredentials, clock: ClockPort | None
) -> BybitSigner:
    return BybitSigner(
        credentials,
        clock or SystemClock(),
        recv_window_ms=settings.bybit_recv_window_ms,
    )


@asynccontextmanager
async def _http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """One transport configuration for every client.

    The timeout is not a tuning knob: Bybit rejects a request whose timestamp
    falls outside ``recv_window`` of its own clock, so a call that outlives
    that window can never succeed on retry anyway.
    """
    async with httpx.AsyncClient(
        base_url=settings.bybit_base_url,
        timeout=settings.bybit_timeout_seconds,
    ) as http:
        yield http

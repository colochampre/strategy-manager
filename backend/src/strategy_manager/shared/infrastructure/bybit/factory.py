"""Builds configured Bybit clients.

Credentials are passed in rather than read here: the single envelope-encrypted
vault credential (CLAUDE.md rule 8, design decision 18) is the only source for
every caller now, worker and probe alike. This module used to also read a
second, `.env`-configured read-only pair via its own ``credentials_from_settings``;
that source is retired, along with the `.env` key it read.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.bybit.read_client import BybitReadOnlyClient
from strategy_manager.shared.infrastructure.bybit.signer import (
    BybitCredentials,
    BybitSigner,
)
from strategy_manager.shared.infrastructure.bybit.trade_client import BybitTradeClient
from strategy_manager.shared.infrastructure.bybit.transport import BybitTransport
from strategy_manager.shared.infrastructure.clock import SystemClock


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

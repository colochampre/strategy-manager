"""Builds configured Binance transports.

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
from strategy_manager.shared.infrastructure.binance.read_client import (
    BinanceReadOnlyClient,
)
from strategy_manager.shared.infrastructure.binance.signer import (
    BinanceCredentials,
    BinanceSigner,
)
from strategy_manager.shared.infrastructure.binance.trade_client import BinanceTradeClient
from strategy_manager.shared.infrastructure.binance.transport import BinanceTransport
from strategy_manager.shared.infrastructure.clock import SystemClock


@asynccontextmanager
async def futures_transport(
    settings: Settings,
    credentials: BinanceCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BinanceTransport]:
    """USDⓈ-M futures: ``fapi.binance.com``."""
    async with _transport(settings.binance_futures_base_url, settings, credentials, clock) as t:
        yield t


@asynccontextmanager
async def read_only_client(
    settings: Settings,
    credentials: BinanceCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BinanceReadOnlyClient]:
    """Yields a read-only USDⓈ-M futures client bound to these credentials.

    Deliberately separate from the transports below: a caller asking for this
    one cannot reach an endpoint that writes, because the client has no method
    that does.
    """
    signer = BinanceSigner(
        credentials,
        clock or SystemClock(),
        recv_window_ms=settings.binance_recv_window_ms,
    )
    async with httpx.AsyncClient(
        base_url=settings.binance_futures_base_url,
        timeout=settings.binance_timeout_seconds,
    ) as http:
        yield BinanceReadOnlyClient(http, signer)


@asynccontextmanager
async def trade_client(
    settings: Settings,
    credentials: BinanceCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BinanceTradeClient]:
    """Yields a USDⓈ-M futures client that can place orders.

    Deliberately a separate entry point from ``read_only_client``, exactly as
    on Bybit. Anything that only reads should be unable to reach a writing
    client by accident, and a call site asking for this one is stating plainly
    that it intends to move money.

    Which credentials arrive here is the caller's decision and it is not a
    detail: a key that cannot trade (decision 18's "accepted with a warning"
    read-only case) would come back as ``-2015`` — a code that also means a
    revoked key and a host outside the allowlist, and therefore reads like the
    venue refusing the write rather than like the wrong capability being used.
    """
    signer = BinanceSigner(
        credentials,
        clock or SystemClock(),
        recv_window_ms=settings.binance_recv_window_ms,
    )
    async with httpx.AsyncClient(
        base_url=settings.binance_futures_base_url,
        timeout=settings.binance_timeout_seconds,
    ) as http:
        yield BinanceTradeClient(http, signer)


@asynccontextmanager
async def spot_transport(
    settings: Settings,
    credentials: BinanceCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[BinanceTransport]:
    """Spot and account-wide wallet endpoints: ``api.binance.com``."""
    async with _transport(settings.binance_spot_base_url, settings, credentials, clock) as t:
        yield t


@asynccontextmanager
async def _transport(
    base_url: str,
    settings: Settings,
    credentials: BinanceCredentials,
    clock: ClockPort | None,
) -> AsyncIterator[BinanceTransport]:
    signer = BinanceSigner(
        credentials,
        clock or SystemClock(),
        recv_window_ms=settings.binance_recv_window_ms,
    )
    async with httpx.AsyncClient(
        base_url=base_url, timeout=settings.binance_timeout_seconds
    ) as http:
        yield BinanceTransport(http, signer)

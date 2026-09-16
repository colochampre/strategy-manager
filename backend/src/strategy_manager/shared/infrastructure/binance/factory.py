"""Builds configured Binance transports.

Credentials are passed in rather than read here, for the reason the Bybit and
Pionex factories give: the environment holds a read-only key for probes and
balance reads, the vault holds the key that signs orders, and neither may
silently stand in for the other.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
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


def credentials_from_settings(settings: Settings) -> BinanceCredentials:
    """Reads the environment-configured key pair, refusing to send an
    unauthenticated request that would only come back as a signature error."""
    if not settings.binance_api_key or not settings.binance_api_secret:
        raise InvariantViolation(
            "BINANCE_API_KEY and BINANCE_API_SECRET must be set to read Binance "
            "account state from the environment"
        )
    return BinanceCredentials(
        api_key=settings.binance_api_key,
        api_secret=settings.binance_api_secret,
    )


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
    detail: the vault's trade key signs orders, while the environment's
    read-only key would come back as ``-2015`` — a code that also means a
    revoked key and a host outside the allowlist, and therefore reads like the
    venue refusing the write rather than like the wrong key being used.
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

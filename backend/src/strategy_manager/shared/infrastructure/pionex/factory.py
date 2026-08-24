"""Builds a configured read-only Pionex client.

Credentials are passed in rather than read here, because there are two
legitimate sources and they are not interchangeable. The worker loads them
from the envelope-encrypted vault, which is the system of record. The
standalone probe script reads them from the environment, which is a developer
convenience and never signs an order.

Keeping the choice at the call site means neither source can silently stand
in for the other.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.pionex.futures_read_client import (
    PionexFuturesReadClient,
)
from strategy_manager.shared.infrastructure.pionex.read_client import PionexReadOnlyClient
from strategy_manager.shared.infrastructure.pionex.signer import (
    PionexCredentials,
    PionexSigner,
)
from strategy_manager.shared.infrastructure.pionex.trade_client import PionexTradeClient


def credentials_from_settings(settings: Settings) -> PionexCredentials:
    """Reads the environment-configured key pair.

    Raises rather than letting an unauthenticated request reach Pionex and
    come back as an opaque signature failure.
    """
    if not settings.pionex_api_key or not settings.pionex_api_secret:
        raise InvariantViolation(
            "PIONEX_API_KEY and PIONEX_API_SECRET must be set to read Pionex "
            "account state from the environment"
        )
    return PionexCredentials(
        api_key=settings.pionex_api_key,
        api_secret=settings.pionex_api_secret,
    )


@asynccontextmanager
async def read_only_client(
    settings: Settings,
    credentials: PionexCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[PionexReadOnlyClient]:
    """Yields a read-only client bound to the supplied credentials."""
    signer = PionexSigner(credentials, clock or SystemClock())

    async with _http(settings) as http:
        yield PionexReadOnlyClient(http, signer)


@asynccontextmanager
async def futures_read_only_client(
    settings: Settings,
    credentials: PionexCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[PionexFuturesReadClient]:
    """Yields a read-only futures client bound to the supplied credentials.

    Separate from ``read_only_client`` because the two speak to different
    base paths and return different read models, not because one is safer:
    both are GET-only by construction.
    """
    signer = PionexSigner(credentials, clock or SystemClock())

    async with _http(settings) as http:
        yield PionexFuturesReadClient(http, signer)


@asynccontextmanager
async def trade_client(
    settings: Settings,
    credentials: PionexCredentials,
    clock: ClockPort | None = None,
) -> AsyncIterator[PionexTradeClient]:
    """Yields a client that can place orders.

    Deliberately a separate entry point from ``read_only_client``. Anything
    that only reads should be unable to reach a writing client by accident,
    and a call site asking for this one is stating plainly that it intends to
    move money.
    """
    signer = PionexSigner(credentials, clock or SystemClock())

    async with _http(settings) as http:
        yield PionexTradeClient(http, signer)


@asynccontextmanager
async def _http(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """One transport configuration for both clients.

    The timeout is not a tuning knob: Pionex rejects a request whose timestamp
    is more than 20s off its own clock, so a call that outlives that window
    can never succeed on retry anyway.
    """
    async with httpx.AsyncClient(
        base_url=settings.pionex_base_url,
        timeout=settings.pionex_timeout_seconds,
    ) as http:
        yield http

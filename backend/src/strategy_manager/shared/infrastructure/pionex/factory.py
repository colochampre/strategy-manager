"""Builds a configured read-only Pionex client from ``Settings``.

Kept apart from the client itself so the client stays free of configuration
concerns and remains trivially constructible in tests with a mock transport.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import Settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.pionex.read_client import PionexReadOnlyClient
from strategy_manager.shared.infrastructure.pionex.signer import (
    PionexCredentials,
    PionexSigner,
)


@asynccontextmanager
async def read_only_client(
    settings: Settings, clock: ClockPort | None = None
) -> AsyncIterator[PionexReadOnlyClient]:
    """Yields a read-only client bound to the configured credentials.

    Raises ``InvariantViolation`` when credentials are missing rather than
    letting an unauthenticated request reach Pionex and come back as an
    opaque signature failure.
    """
    if not settings.pionex_api_key or not settings.pionex_api_secret:
        raise InvariantViolation(
            "PIONEX_API_KEY and PIONEX_API_SECRET must be set to read Pionex account state"
        )

    credentials = PionexCredentials(
        api_key=settings.pionex_api_key,
        api_secret=settings.pionex_api_secret,
    )
    signer = PionexSigner(credentials, clock or SystemClock())

    async with httpx.AsyncClient(
        base_url=settings.pionex_base_url,
        timeout=settings.pionex_timeout_seconds,
    ) as http:
        yield PionexReadOnlyClient(http, signer)

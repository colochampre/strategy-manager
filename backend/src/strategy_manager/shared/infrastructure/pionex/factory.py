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
from strategy_manager.shared.infrastructure.pionex.read_client import PionexReadOnlyClient
from strategy_manager.shared.infrastructure.pionex.signer import (
    PionexCredentials,
    PionexSigner,
)


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

    async with httpx.AsyncClient(
        base_url=settings.pionex_base_url,
        timeout=settings.pionex_timeout_seconds,
    ) as http:
        yield PionexReadOnlyClient(http, signer)

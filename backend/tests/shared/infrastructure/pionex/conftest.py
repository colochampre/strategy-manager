from datetime import UTC, datetime

import pytest

from strategy_manager.shared.infrastructure.pionex.signer import (
    PionexCredentials,
    PionexSigner,
)

API_KEY = "test-key-abcd"
API_SECRET = "test-secret"

# Any fixed instant works; what matters is that the signer reads the injected
# clock, so the signed timestamp is reproducible instead of wall-clock noise.
FROZEN_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


class FrozenClock:
    """Implements ``ClockPort`` with a fixed instant."""

    def __init__(self, now: datetime = FROZEN_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@pytest.fixture
def api_secret() -> str:
    return API_SECRET


@pytest.fixture
def timestamp_ms() -> int:
    return int(FROZEN_NOW.timestamp() * 1000)


@pytest.fixture
def credentials() -> PionexCredentials:
    return PionexCredentials(api_key=API_KEY, api_secret=API_SECRET)


@pytest.fixture
def signer(credentials: PionexCredentials) -> PionexSigner:
    return PionexSigner(credentials, FrozenClock())

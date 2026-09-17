"""Integration test: main.py's lifespan wires CapitalPoolRepository +
assert_pool_lock_keys_distinct together at startup (tasks.md 3.15 — invariant
1), and refuses to start without a webhook secret (invariant 3). Placed here
because it needs the seeded-pools ``pg_engine`` fixture.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager import main
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation

pytestmark = pytest.mark.integration

SECRET = "test-webhook-secret"


@pytest.fixture
def _configure_webhook_secret() -> Iterator[None]:
    """Set explicitly rather than inherited from the developer's .env, so
    invariant 3 is exercised by the test and not by the machine."""
    settings = get_settings()
    previous = settings.webhook_secret
    settings.webhook_secret = SECRET
    yield
    settings.webhook_secret = previous


async def test_lifespan_passes_against_real_seeded_pools(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    _configure_webhook_secret: None,
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)

    async with main.lifespan(main.app):
        pass  # no exception raised means the invariants passed


async def test_lifespan_refuses_to_start_without_a_webhook_secret(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the API mounts an endpoint that answers 401 to every alert it
    was deployed to receive, and reports nothing as broken."""
    monkeypatch.setattr(main, "engine", pg_engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "")

    with pytest.raises(InvariantViolation, match="WEBHOOK_SECRET is not set"):
        async with main.lifespan(main.app):
            pass  # pragma: no cover - the invariant aborts before the body

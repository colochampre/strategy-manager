"""Integration test: main.py's lifespan wires CapitalPoolRepository +
assert_pool_lock_keys_distinct together at startup (tasks.md 3.15 — invariant
1), refuses to start without a webhook secret (invariant 3), and refuses to
start without an admin API token (invariant 4). The panel
directory check is exercised in ``tests/shared/test_startup_invariants.py``.
Placed here because it needs
the seeded-pools ``pg_engine`` fixture.
"""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager import main
from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation

pytestmark = pytest.mark.integration

SECRET = "test-webhook-secret"
ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def _configure_startup_secrets() -> Iterator[None]:
    """Set explicitly rather than inherited from the developer's .env, so
    invariants 3 and 4 are exercised by the test and not by the machine.

    All of them, because the lifespan asserts all: a test that satisfied only
    some would report the OTHER invariant's abort as a failure of the wiring
    it was actually written to check (the panel directory is reset too, so a
    developer's PANEL_DIST_DIR cannot refuse the start)."""
    settings = get_settings()
    previous_secret = settings.webhook_secret
    previous_token = settings.admin_api_token
    previous_panel_dir = settings.panel_dist_dir
    settings.webhook_secret = SECRET
    settings.admin_api_token = ADMIN_TOKEN
    settings.panel_dist_dir = ""
    yield
    settings.webhook_secret = previous_secret
    settings.admin_api_token = previous_token
    settings.panel_dist_dir = previous_panel_dir


async def test_lifespan_passes_against_real_seeded_pools(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    _configure_startup_secrets: None,
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
    monkeypatch.setattr(settings, "admin_api_token", ADMIN_TOKEN)
    monkeypatch.setattr(settings, "webhook_secret", "")

    with pytest.raises(InvariantViolation, match="WEBHOOK_SECRET is not set"):
        async with main.lifespan(main.app):
            pass  # pragma: no cover - the invariant aborts before the body


async def test_lifespan_refuses_to_start_without_an_admin_api_token(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the API mounts the router that registers and arms strategies
    behind an authentication whose expected value is empty, and looks healthy
    while doing it.

    The webhook secret is set here so the abort under test is unambiguously
    invariant 4's: with both empty, invariant 3 aborts first and this test
    would pass without the token ever being checked."""
    monkeypatch.setattr(main, "engine", pg_engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    monkeypatch.setattr(settings, "admin_api_token", "")

    with pytest.raises(InvariantViolation, match="ADMIN_API_TOKEN is not set"):
        async with main.lifespan(main.app):
            pass  # pragma: no cover - the invariant aborts before the body


async def test_an_unusable_master_key_does_not_stop_the_api_from_starting(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    _configure_startup_secrets: None,
) -> None:
    """Owner decision (2026-09-30), design K5: there is NO startup invariant for
    ``MASTER_ENCRYPTION_KEY``. This process also hosts ``POST /webhook/tradingview``,
    so refusing to boot over a fault only ``PUT /api/credentials/{exchange}`` has
    would stop signal ingestion entirely and loop under ``Restart=always``. The
    worker refuses a bad key on its own (exit 78). The PUT's own 503 and its one
    ERROR are pinned in ``test_credentials_router.py``.
    """
    monkeypatch.setattr(main, "engine", pg_engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "master_encryption_key", "")

    async with main.lifespan(main.app), AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        health = await api.get("/health")
        webhook = await api.post("/webhook/tradingview", json={"not": "a signal"})
        save = await api.put(
            "/api/credentials/bybit",
            json={"api_key": "abcd1234", "api_secret": "s"},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )

    assert health.status_code == 200
    assert webhook.status_code < 500  # refused as a bad request, not a server fault
    assert save.status_code == 503

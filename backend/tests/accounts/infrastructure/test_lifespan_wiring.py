"""Integration test: main.py's lifespan wires CapitalPoolRepository +
assert_pool_lock_keys_distinct together at startup (tasks.md 3.15 — invariant
1), refuses to start without a webhook secret (invariant 3), and refuses to
start without an identity configuration (invariant 4). The panel
directory check is exercised in ``tests/shared/test_startup_invariants.py``.
Placed here because it needs
the seeded-pools ``pg_engine`` fixture.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation

pytestmark = pytest.mark.integration

SECRET = "test-webhook-secret"
ADMIN_EMAIL = "owner@example.com"


def _configure_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local, dry-run identity: every request is ``DEV_USER_EMAIL``, which is
    the admin. The Access values are cleared so a developer's .env cannot put
    them beside ``DEV_USER_EMAIL``, which invariant 4 refuses."""
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_email", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "dev_user_email", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "access_team_domain", "")
    monkeypatch.setattr(settings, "access_aud", "")
    monkeypatch.setattr(settings, "dry_run", True)


@pytest.fixture
def _configure_startup_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set explicitly rather than inherited from the developer's .env, so
    invariants 3 and 4 are exercised by the test and not by the machine.

    All of them, because the lifespan asserts all: a test that satisfied only
    some would report the OTHER invariant's abort as a failure of the wiring
    it was actually written to check (the panel directory is reset too, so a
    developer's PANEL_DIST_DIR cannot refuse the start)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    _configure_identity(monkeypatch)
    monkeypatch.setattr(settings, "panel_dist_dir", "")


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
    _configure_identity(monkeypatch)
    monkeypatch.setattr(settings, "webhook_secret", "")

    with pytest.raises(InvariantViolation, match="WEBHOOK_SECRET is not set"):
        async with main.lifespan(main.app):
            pass  # pragma: no cover - the invariant aborts before the body


async def test_lifespan_refuses_to_start_without_an_admin_email(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the API mounts the router that registers and arms strategies
    behind a guard with no admin to compare against, and looks healthy while
    doing it.

    The webhook secret and the rest of the identity are set here so the abort
    under test is unambiguously ``ADMIN_EMAIL``'s: with the secret empty,
    invariant 3 aborts first and this test would pass without the admin ever
    being checked."""
    monkeypatch.setattr(main, "engine", pg_engine)
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", SECRET)
    _configure_identity(monkeypatch)
    monkeypatch.setattr(settings, "admin_email", "")

    with pytest.raises(InvariantViolation, match="ADMIN_EMAIL is not set"):
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

    app = create_app()
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)

    async def _session() -> AsyncIterator[AsyncSession]:
        # ``PUT /api/credentials`` resolves the signed-in ``User`` (B.6): from the
        # test database, not from whatever the developer's ``DATABASE_URL`` holds.
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session

    async with main.lifespan(main.app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as api:
        health = await api.get("/health")
        webhook = await api.post("/webhook/tradingview", json={"not": "a signal"})
        # No assertion header: ``DEV_USER_EMAIL`` signs every request in as
        # the admin, so the 503 below is the PUT's own, not the guard's.
        save = await api.put(
            "/api/credentials/bybit",
            json={"api_key": "abcd1234", "api_secret": "s"},
        )

    assert health.status_code == 200
    assert webhook.status_code < 500  # refused as a bad request, not a server fault
    assert save.status_code == 503

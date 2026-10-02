"""The suite must be unable to reach Telegram through a developer's local settings.

``get_settings()`` reads ``backend/.env``. On a machine where operator alerts
are configured there, any test that enters the real ``main.lifespan`` installs
an ``AlertLogBridge`` on the ROOT logger, and every ERROR that test then logs
on purpose is delivered to the real chat. The autouse fixture in
``tests/conftest.py`` turns alerts off on that settings object; these tests pin
the outcome, never sending anything themselves.
"""

import logging
from collections.abc import Iterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager import main
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.alert_log_bridge import AlertLogBridge
from strategy_manager.shared.infrastructure.alerting import (
    build_alerter,
    operator_alerts,
)


def _bridges_on_root() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if isinstance(h, AlertLogBridge)]


def test_the_shared_settings_build_no_alerter() -> None:
    # Bound to a name first: an assertion that calls ``get_settings()`` inline
    # would print the whole settings object, DSN included, when it fails.
    alerter = build_alerter(get_settings())

    assert alerter is None


async def test_operator_alerts_on_the_shared_settings_installs_no_bridge() -> None:
    async with operator_alerts(get_settings()) as bridge:
        assert bridge is None
        assert _bridges_on_root() == []


@pytest.fixture
def _startup_secrets(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(settings, "admin_api_token", "test-admin-token")
    monkeypatch.setattr(settings, "panel_dist_dir", "")
    yield


@pytest.mark.integration
async def test_the_real_lifespan_installs_no_bridge_on_the_root_logger(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    _startup_secrets: None,
) -> None:
    """The scenario that sent the alert: the real lifespan, with the master key
    emptied, so a later PUT logs its one intended ERROR."""
    monkeypatch.setattr(main, "engine", pg_engine)
    monkeypatch.setattr(get_settings(), "master_encryption_key", "")

    async with main.lifespan(main.app):
        assert _bridges_on_root() == []

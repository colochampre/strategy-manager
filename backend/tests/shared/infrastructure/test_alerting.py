"""Where alerting is turned on, and every way it must stay off.

The whole feature is opt-in, and the reason is that the failure modes of a
half-configured alert channel are worse than having none. A deployment that
sets nothing must behave exactly as it did before this existed; a deployment
that sets the flag but forgets the token must say so once and then keep
running, because a worker that refuses to start over its own notification
channel has made the alerting more dangerous than the silence.
"""

import inspect
import logging

import pytest

from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.alert_log_bridge import AlertLogBridge
from strategy_manager.shared.infrastructure.alerting import (
    build_alerter,
    operator_alerts,
)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "alerts_enabled": True,
        "telegram_bot_token": "8123456789:AAH1z_kQm0pQrStUvWxYz012345678ab",
        "telegram_chat_id": "-1001234567890",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def _bridges_on_root() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if isinstance(h, AlertLogBridge)]


def test_no_alerter_is_built_when_alerting_is_off() -> None:
    assert build_alerter(_settings(alerts_enabled=False)) is None


def test_no_alerter_is_built_without_a_token() -> None:
    assert build_alerter(_settings(telegram_bot_token="")) is None


def test_no_alerter_is_built_without_a_chat_id() -> None:
    assert build_alerter(_settings(telegram_chat_id="")) is None


def test_a_half_configured_channel_says_so_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Enabled but missing a credential is a mistake, and a silent one would
    leave the operator believing the phone will ring."""
    with caplog.at_level(logging.WARNING):
        assert build_alerter(_settings(telegram_chat_id="")) is None

    assert any("TELEGRAM_CHAT_ID" in r.getMessage() for r in caplog.records)


def test_the_warning_about_a_missing_token_never_prints_the_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        build_alerter(_settings(telegram_chat_id=""))

    for record in caplog.records:
        assert "8123456789" not in record.getMessage()


def test_a_configured_channel_builds_an_alerter() -> None:
    alerter = build_alerter(_settings())

    assert alerter is not None
    assert alerter.timeout_seconds == Settings(_env_file=None).alert_send_timeout_seconds


async def test_alerting_off_installs_nothing() -> None:
    before = len(_bridges_on_root())

    async with operator_alerts(_settings(alerts_enabled=False)) as bridge:
        assert bridge is None
        assert len(_bridges_on_root()) == before


async def test_alerting_on_installs_a_bridge_on_the_root_logger() -> None:
    """The ROOT logger, so every module's ERROR is covered without each one
    having to opt in. A per-logger install is a list that silently stops being
    complete the first time a module is added."""
    async with operator_alerts(_settings()) as bridge:
        assert bridge is not None
        assert bridge in _bridges_on_root()

    assert bridge not in _bridges_on_root()


async def test_the_bridge_is_removed_even_when_the_body_raises() -> None:
    """A handler left attached to a closed bridge turns every later ERROR
    into a dropped alert, for the life of the process."""
    leaked: AlertLogBridge | None = None

    with pytest.raises(RuntimeError):
        async with operator_alerts(_settings()) as bridge:
            leaked = bridge
            raise RuntimeError("the worker fell over")

    assert leaked is not None
    assert leaked not in _bridges_on_root()
    assert leaked.closed


async def test_the_installed_bridge_carries_the_configured_throttle_window() -> None:
    async with operator_alerts(_settings(alert_throttle_window_seconds=42.0)) as bridge:
        assert bridge is not None
        assert bridge.throttle_window_seconds == 42.0


async def test_alerting_is_independent_of_dry_run() -> None:
    """Deliberately not gated on DRY_RUN. This is about whether the SYSTEM is
    healthy, not about whether it is trading — a rehearsal whose balance sync
    is dead is just as broken, and is exactly where it would be noticed."""
    async with operator_alerts(_settings(dry_run=True)) as bridge:
        assert bridge is not None


def test_both_entry_points_install_the_bridge() -> None:
    """A structural assertion, and a deliberate one. The composition inside
    ``worker.run`` and the API lifespan cannot be exercised without a live
    database, so what is pinned here is that neither entry point quietly
    stops installing alerting — the failure this whole unit exists to make
    impossible is a channel that is silently not there."""
    from strategy_manager import main, worker

    assert "operator_alerts" in inspect.getsource(worker.run)
    assert "operator_alerts" in inspect.getsource(main.lifespan)

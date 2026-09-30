"""The API's startup refusal added with the panel (tasks 4b.5 and 4b.7).

``PANEL_DIST_DIR``, when set, must hold an ``index.html``. There is deliberately
NO invariant for ``MASTER_ENCRYPTION_KEY`` (design K5, owner decision 2026-09-30):
see ``test_lifespan_wiring.py`` for the test that pins its absence.

The refusal is NEVER SILENT (owner decision 29, design note on the API's lifespan).
uvicorn reports a failed lifespan on its own ``uvicorn`` logger, which has
``propagate=False``, so that ERROR never reaches the root logger the alert bridge
listens on. A refusal that only raised would therefore reach no alert channel, and
under ``Restart=always`` would loop without anyone being told. So it logs ONE
ERROR through an application logger, before raising. ``caplog`` hangs its handler
on the ROOT logger, which is exactly where the bridge is installed, so a record
that appears there is a record that would have been forwarded.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager import main
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.spa import assert_panel_dist_ready
from tests.ledger.infrastructure.conftest import pg_engine  # noqa: F401


def _settings(**values: object) -> Settings:
    """Built without reading .env, so these describe the code and not whatever
    the developer's machine happens to be configured with."""
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


# --- PANEL_DIST_DIR --------------------------------------------------------------


def test_an_unset_panel_dist_dir_is_not_checked_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert_panel_dist_ready(_settings(panel_dist_dir=""))

    assert _errors(caplog) == []


def test_a_panel_dist_dir_with_an_index_html_starts(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")

    with caplog.at_level(logging.DEBUG):
        assert_panel_dist_ready(_settings(panel_dist_dir=str(tmp_path)))

    assert _errors(caplog) == []


def test_panel_dist_dir_set_but_index_html_missing_refuses_to_start(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(
        InvariantViolation, match="PANEL_DIST_DIR"
    ):
        assert_panel_dist_ready(_settings(panel_dist_dir=str(tmp_path)))

    errors = _errors(caplog)
    assert len(errors) == 1
    assert "index.html" in errors[0].getMessage()
    assert "refusing to start" in errors[0].getMessage()


def test_a_panel_dist_dir_that_does_not_exist_refuses_to_start(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(InvariantViolation):
        assert_panel_dist_ready(_settings(panel_dist_dir=str(tmp_path / "no-such-dir")))

    assert len(_errors(caplog)) == 1


def test_an_index_html_that_is_a_directory_refuses_to_start(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "index.html").mkdir()

    with caplog.at_level(logging.DEBUG), pytest.raises(InvariantViolation):
        assert_panel_dist_ready(_settings(panel_dist_dir=str(tmp_path)))

    assert len(_errors(caplog)) == 1


def test_panel_dist_dir_defaults_to_empty_so_nothing_is_mounted() -> None:
    assert _settings().panel_dist_dir == ""


# --- through the real lifespan ---------------------------------------------------

@pytest.fixture
def _startup_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Everything the lifespan checks before the panel directory, set explicitly."""
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(settings, "admin_api_token", "test-admin-token")
    monkeypatch.setattr(settings, "panel_dist_dir", "")
    yield


class _RootCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def alert_bridge_standin(monkeypatch: pytest.MonkeyPatch) -> _RootCapture:
    """Replaces ``operator_alerts`` with a context that installs a handler on the
    ROOT logger for its duration, as the real bridge does. A record it holds was
    therefore logged through a logger that propagates to root AND while the
    bridge was installed: the two conditions under which a real alert is sent."""
    capture = _RootCapture()

    @asynccontextmanager
    async def installed(settings: Settings) -> AsyncIterator[None]:
        del settings
        root = logging.getLogger()
        root.addHandler(capture)
        try:
            yield
        finally:
            root.removeHandler(capture)

    monkeypatch.setattr(main, "operator_alerts", installed)
    return capture


@pytest.mark.integration
async def test_the_lifespan_passes_with_a_usable_key_and_no_panel(
    pg_engine: AsyncEngine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    _startup_configured: None,
    alert_bridge_standin: _RootCapture,
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)

    async with main.lifespan(main.app):
        pass

    assert alert_bridge_standin.records == []


@pytest.mark.integration
async def test_the_lifespan_refuses_a_panel_dir_without_index_html_and_the_error_reaches_root(
    pg_engine: AsyncEngine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    _startup_configured: None,
    alert_bridge_standin: _RootCapture,
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)
    monkeypatch.setattr(get_settings(), "panel_dist_dir", str(tmp_path))

    with pytest.raises(InvariantViolation):
        async with main.lifespan(main.app):
            pass  # pragma: no cover - the invariant aborts before the body

    records = alert_bridge_standin.records
    assert len(records) == 1
    assert "index.html" in records[0].getMessage()

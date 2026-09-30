"""The API's startup refusals added with the panel (tasks 4b.5 and 4b.7).

- Invariant 5: ``EnvelopeCipher.from_base64(MASTER_ENCRYPTION_KEY)`` must succeed.
- ``PANEL_DIST_DIR``, when set, must hold an ``index.html``.

Both are NEVER SILENT (owner decision 29, design note on the API's lifespan).
uvicorn reports a failed lifespan on its own ``uvicorn`` logger, which has
``propagate=False``, so that ERROR never reaches the root logger the alert bridge
listens on. A refusal that only raised would therefore reach no alert channel, and
under ``Restart=always`` would loop without anyone being told. So each refusal logs
ONE ERROR through an application logger, before raising. ``caplog`` hangs its
handler on the ROOT logger, which is exactly where the bridge is installed, so a
record that appears there is a record that would have been forwarded.

The key is a credential-grade secret: no message may contain any part of it.
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
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES
from strategy_manager.shared.infrastructure.master_key_invariant import (
    assert_master_key_usable,
)
from strategy_manager.shared.infrastructure.spa import assert_panel_dist_ready
from tests.ledger.infrastructure.conftest import pg_engine  # noqa: F401

VALID_KEY = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU="  # 32 bytes of ASCII
SENTINEL_BAD_BASE64 = "sentinel-KEY-material!!not-base64"
SENTINEL_SHORT_KEY = "c2hvcnQta2V5LXNlbnRpbmVsLXRvby1zaG9ydA=="  # valid base64, wrong length


def _settings(**values: object) -> Settings:
    """Built without reading .env, so these describe the code and not whatever
    the developer's machine happens to be configured with."""
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def _assert_no_part_of(secret: str, records: list[logging.LogRecord]) -> None:
    """No window of eight characters of ``secret`` appears anywhere a record can
    carry text: the message, its arguments, or an attached traceback."""
    haystack = " ".join(
        [record.getMessage() for record in records]
        + [str(record.args) for record in records]
        + [str(record.exc_info) for record in records]
        + [str(record.exc_text) for record in records]
    )
    for start in range(len(secret) - 7):
        window = secret[start : start + 8]
        assert window not in haystack, f"part of the key reached a log record: {window!r}"


# --- invariant 5 -----------------------------------------------------------------


def test_a_usable_master_key_starts_and_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert_master_key_usable(_settings(master_encryption_key=VALID_KEY))

    assert _errors(caplog) == []


def test_missing_master_encryption_key_refuses_to_start_invariant_5(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(
        InvariantViolation, match="MASTER_ENCRYPTION_KEY"
    ):
        assert_master_key_usable(_settings(master_encryption_key=""))

    errors = _errors(caplog)
    assert len(errors) == 1
    assert "MASTER_ENCRYPTION_KEY" in errors[0].getMessage()
    assert "refusing to start" in errors[0].getMessage()


@pytest.mark.parametrize("key", [SENTINEL_BAD_BASE64, SENTINEL_SHORT_KEY])
def test_an_unusable_master_key_refuses_and_its_error_carries_no_part_of_the_key(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(InvariantViolation):
        assert_master_key_usable(_settings(master_encryption_key=key))

    errors = _errors(caplog)
    assert len(errors) == 1
    assert errors[0].exc_info is None
    _assert_no_part_of(key, caplog.records)


def test_the_master_key_error_is_raised_with_no_part_of_the_key_either() -> None:
    with pytest.raises(InvariantViolation) as refused:
        assert_master_key_usable(_settings(master_encryption_key=SENTINEL_SHORT_KEY))

    assert SENTINEL_SHORT_KEY[:8] not in str(refused.value)
    assert MASTER_KEY_BYTES == 32  # the length the valid fixture key is built to


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
    """Everything the lifespan checks before invariant 5, set explicitly."""
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(settings, "admin_api_token", "test-admin-token")
    monkeypatch.setattr(settings, "master_encryption_key", VALID_KEY)
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
async def test_the_lifespan_refuses_an_unusable_master_key_and_the_error_reaches_root(
    pg_engine: AsyncEngine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    _startup_configured: None,
    alert_bridge_standin: _RootCapture,
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)
    monkeypatch.setattr(get_settings(), "master_encryption_key", SENTINEL_BAD_BASE64)

    with pytest.raises(InvariantViolation):
        async with main.lifespan(main.app):
            pass  # pragma: no cover - the invariant aborts before the body

    records = alert_bridge_standin.records
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert "MASTER_ENCRYPTION_KEY" in records[0].getMessage()
    _assert_no_part_of(SENTINEL_BAD_BASE64, records)


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

"""The startup line of ``WEBHOOK_PUBLIC_ORIGIN`` (design.md, unit 12f addendum,
section J; tasks.md 12f.9.5).

``log_webhook_origin`` logs exactly one line from its own logger and never
raises:

- unset: INFO, saying the panel shows the path only;
- well formed: INFO with the NORMALISED origin;
- malformed: ERROR naming the setting and a fixed reason, NEVER the value.

It is ERROR, not WARNING, because on screen a malformed value cannot be told
from an unset one, and only ERROR reaches the alert channel. It is deliberately
NOT a startup invariant: the process that would refuse to start is the one that
receives the alerts (rule 3).

``caplog`` hangs its handler on the ROOT logger, which is where the alert bridge
is installed, so a record seen here is a record that would have been forwarded.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from strategy_manager import main
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.signals.infrastructure.webhook_origin_check import log_webhook_origin
from tests.ledger.infrastructure.conftest import pg_engine  # noqa: F401

LOGGER = "strategy_manager.signals.infrastructure.webhook_origin_check"
CREDENTIAL_ORIGIN = "https://user:pass@example.org"


def _settings(value: str) -> Settings:
    """Built without reading .env, so the test describes the code and not the
    developer's machine."""
    return Settings(_env_file=None, webhook_public_origin=value)  # type: ignore[call-arg]


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == LOGGER]


def _everything_a_record_holds(record: logging.LogRecord) -> str:
    """The message, the arguments and the formatted exception, the three places a
    value could be hiding."""
    parts = [record.getMessage(), str(record.msg), repr(record.args)]
    if record.exc_info is not None:
        parts.append(logging.Formatter().formatException(record.exc_info))
    if record.exc_text:
        parts.append(record.exc_text)
    return "\n".join(parts)


def test_an_unset_setting_logs_one_info_saying_the_panel_shows_the_path_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        log_webhook_origin(_settings(""))

    records = _records(caplog)
    assert [(record.levelno, record.getMessage()) for record in records] == [
        (
            logging.INFO,
            "WEBHOOK_PUBLIC_ORIGIN is not set: the panel shows the webhook path only",
        )
    ]


def test_a_well_formed_value_logs_one_info_with_the_normalised_origin(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        log_webhook_origin(_settings("HTTPS://Example.ORG"))

    records = _records(caplog)
    assert [(record.levelno, record.getMessage()) for record in records] == [
        (
            logging.INFO,
            "WEBHOOK_PUBLIC_ORIGIN is set: the panel builds the webhook URL on "
            "https://example.org",
        )
    ]


def test_a_malformed_value_logs_one_error_naming_the_setting_and_the_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        log_webhook_origin(_settings("ftp://example.org"))

    records = _records(caplog)
    assert [(record.levelno, record.getMessage()) for record in records] == [
        (
            logging.ERROR,
            "WEBHOOK_PUBLIC_ORIGIN is malformed (the scheme must be http or https): "
            "the panel shows the webhook path only",
        )
    ]


def test_no_record_contains_the_raw_value(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        log_webhook_origin(_settings(CREDENTIAL_ORIGIN))

    assert len(_records(caplog)) == 1
    for record in caplog.records:
        held = _everything_a_record_holds(record)
        assert CREDENTIAL_ORIGIN not in held
        assert "user:pass" not in held
        assert "example.org" not in held


def test_a_malformed_value_does_not_raise() -> None:
    raised: BaseException | None = None
    try:
        log_webhook_origin(_settings(CREDENTIAL_ORIGIN))
    except Exception as exc:  # the test is about WHAT is raised, so it keeps it
        raised = exc

    assert raised is None


# --- through the real lifespan ---------------------------------------------------


class _RootCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def _startup_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Everything the lifespan checks, set explicitly."""
    settings = get_settings()
    monkeypatch.setattr(settings, "webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(settings, "admin_api_token", "test-admin-token")
    monkeypatch.setattr(settings, "panel_dist_dir", "")
    yield


@pytest.fixture
def alert_bridge_standin(monkeypatch: pytest.MonkeyPatch) -> _RootCapture:
    """Replaces ``operator_alerts`` with a context that installs a handler on the
    ROOT logger for its duration, as the real bridge does."""
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
async def test_the_lifespan_starts_with_a_malformed_origin_and_logs_the_one_error(
    pg_engine: AsyncEngine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    _startup_configured: None,
    alert_bridge_standin: _RootCapture,
) -> None:
    monkeypatch.setattr(main, "engine", pg_engine)
    monkeypatch.setattr(get_settings(), "webhook_public_origin", CREDENTIAL_ORIGIN)

    async with main.lifespan(main.app):
        pass  # the API started: a typo in a display setting costs no signal

    records = alert_bridge_standin.records
    assert [(record.name, record.levelno) for record in records] == [(LOGGER, logging.ERROR)]
    held = _everything_a_record_holds(records[0])
    assert "WEBHOOK_PUBLIC_ORIGIN" in held
    assert "user:pass" not in held

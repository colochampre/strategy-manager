"""The API process writes its own log lines (task alg.2).

Found by the deploy of PR 12f-1: ``GET /api/webhook-origin`` answered the
configured origin while the journal of that run held no line naming
``WEBHOOK_PUBLIC_ORIGIN``. The worker calls ``logging.basicConfig``; the API
never configured the root logger, and uvicorn's own logging configuration
touches only the ``uvicorn*`` loggers.

**Why every test of what is written runs in a subprocess.** ``caplog`` puts its
own handler on the root logger and sets the level, so it sees a line production
never writes: that is exactly why the existing tests of these lines were green
while the journal was empty. Here a clean interpreter applies uvicorn's real
logging configuration (through ``uvicorn.Config``, so a uvicorn upgrade that
changes it is followed), imports what the API imports, calls what the API
calls, and the test reads the child's stdout and stderr, the two streams
systemd's journal collects.

The one in-process test is the ORDER: it needs the real ``create_app`` and
``lifespan`` and observes the root logger, not what is written.
"""

import logging
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path

import pytest

from strategy_manager import main
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.api_logging import (
    ApiStreamHandler,
    configure_api_logging,
)

_BACKEND = Path(__file__).resolve().parents[3]

# Uvicorn applies its logging configuration when it builds its Config, before it
# imports the application. Importing ``strategy_manager.main`` here runs the
# module-level ``create_app()``, as uvicorn does.
_PREAMBLE = """
import logging
import uvicorn

uvicorn.Config("strategy_manager.main:app")

import strategy_manager.main
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.api_logging import configure_api_logging
from strategy_manager.signals.infrastructure.webhook_origin_check import log_webhook_origin

root = logging.getLogger()
"""

_EMIT_APPLICATION_LINES = """
probe = logging.getLogger("strategy_manager.probe")
probe.info("marker-info")
probe.warning("marker-warning")
probe.error("marker-error")
"""

_EMIT_EVERYTHING = (
    _EMIT_APPLICATION_LINES
    + """
log_webhook_origin(
    Settings(_env_file=None, webhook_public_origin="https://hook.example.org")
)
logging.getLogger("uvicorn.error").info("marker-uvicorn-error")
logging.getLogger("uvicorn.access").info(
    '%s - "%s %s HTTP/%s" %d',
    "127.0.0.1:5000",
    "POST",
    "/webhook/tradingview?secret=hunter2&x=1",
    "1.1",
    200,
)
for name in ("httpx", "httpcore"):
    logging.getLogger(name).info("marker-" + name + "-info")
    logging.getLogger(name).warning("marker-" + name + "-warning")
"""
)

_SCENARIOS = {
    "plain": "configure_api_logging()" + _EMIT_EVERYTHING,
    # What the alert bridge is: a handler on the root logger that, for the
    # purposes of these tests, writes nowhere.
    "bridge_installed_after": (
        "configure_api_logging()\nroot.addHandler(logging.NullHandler())"
        + _EMIT_APPLICATION_LINES
    ),
    # What pytest's capture is: a handler already on the root logger.
    "handler_already_there": (
        "root.addHandler(logging.NullHandler())\nconfigure_api_logging()"
        + _EMIT_APPLICATION_LINES
    ),
    "called_twice": "configure_api_logging()\nconfigure_api_logging()" + _EMIT_APPLICATION_LINES,
}

_WORKER_FORMAT = (
    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (?P<level>[A-Z]+) +(?P<logger>[\w.]+): (?P<text>.*)"
)


@cache
def _written_by(scenario: str) -> tuple[str, ...]:
    """Every line a clean interpreter wrote to stdout and stderr."""
    env = {**os.environ, "PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(
        [sys.executable, "-c", _PREAMBLE + _SCENARIOS[scenario]],
        cwd=_BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    return tuple((completed.stdout + completed.stderr).splitlines())


def _containing(scenario: str, marker: str) -> list[str]:
    return [line for line in _written_by(scenario) if marker in line]


def _in_the_workers_format(line: str, level: str, logger: str, text: str) -> None:
    match = re.fullmatch(_WORKER_FORMAT, line)
    assert match is not None, line
    assert (match["level"], match["logger"], match["text"]) == (level, logger, text)


def test_an_application_info_line_is_written_once_in_the_workers_format() -> None:
    lines = _containing("plain", "marker-info")

    assert len(lines) == 1
    _in_the_workers_format(lines[0], "INFO", "strategy_manager.probe", "marker-info")


@pytest.mark.parametrize(
    ("scenario"),
    ["plain", "bridge_installed_after", "handler_already_there"],
)
@pytest.mark.parametrize(
    ("marker", "level"),
    [("marker-info", "INFO"), ("marker-warning", "WARNING"), ("marker-error", "ERROR")],
)
def test_each_level_is_written_once_whatever_else_sits_on_the_root_logger(
    scenario: str, marker: str, level: str
) -> None:
    lines = _containing(scenario, marker)

    assert len(lines) == 1
    _in_the_workers_format(lines[0], level, "strategy_manager.probe", marker)


def test_the_origins_startup_line_is_written() -> None:
    lines = _containing("plain", "WEBHOOK_PUBLIC_ORIGIN")

    assert len(lines) == 1
    _in_the_workers_format(
        lines[0],
        "INFO",
        "strategy_manager.signals.infrastructure.webhook_origin_check",
        "WEBHOOK_PUBLIC_ORIGIN is set: the panel builds the webhook URL on https://hook.example.org",
    )


@pytest.mark.parametrize("marker", ["marker-info", "marker-warning", "marker-error"])
def test_calling_the_function_twice_writes_each_line_once(marker: str) -> None:
    assert len(_containing("called_twice", marker)) == 1


def test_an_access_line_is_written_once_and_the_webhook_secret_stays_masked() -> None:
    lines = _containing("plain", "/webhook/tradingview")

    assert len(lines) == 1
    assert "secret=REDACTED" in lines[0]
    assert "hunter2" not in "\n".join(_written_by("plain"))


def test_a_uvicorn_error_line_is_written_once() -> None:
    assert len(_containing("plain", "marker-uvicorn-error")) == 1


@pytest.mark.parametrize("client", ["httpx", "httpcore"])
def test_a_http_client_info_line_is_not_written_but_its_warning_is(client: str) -> None:
    """The Telegram URL holds the bot token and a Binance URL its signature."""
    assert _containing("plain", f"marker-{client}-info") == []
    warnings = _containing("plain", f"marker-{client}-warning")
    assert len(warnings) == 1
    _in_the_workers_format(warnings[0], "WARNING", client, f"marker-{client}-warning")


@pytest.fixture
def clean_root_logger() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    level = root.level
    handlers = list(root.handlers)
    yield root
    root.handlers[:] = handlers
    root.setLevel(level)


def test_the_function_keeps_exactly_one_handler_of_its_own(
    clean_root_logger: logging.Logger,
) -> None:
    configure_api_logging()
    configure_api_logging()

    ours = [h for h in clean_root_logger.handlers if isinstance(h, ApiStreamHandler)]
    assert len(ours) == 1
    assert clean_root_logger.level == logging.INFO


class _Stop(Exception):
    pass


async def test_the_lifespan_configures_logging_before_operator_alerts_install_their_bridge(
    clean_root_logger: logging.Logger, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real ``create_app`` and the real ``lifespan``. The stand-in for
    ``operator_alerts`` records what the root logger looks like at the moment it
    would install the bridge, then stops the start-up."""
    seen: dict[str, object] = {}

    @asynccontextmanager
    async def stand_in(settings: Settings) -> AsyncIterator[None]:
        del settings
        seen["own_handler"] = any(
            isinstance(h, ApiStreamHandler) for h in clean_root_logger.handlers
        )
        seen["level"] = clean_root_logger.level
        raise _Stop
        yield  # pragma: no cover

    monkeypatch.setattr(main, "operator_alerts", stand_in)
    app = main.create_app()

    with pytest.raises(_Stop):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover - the stand-in aborts first

    assert seen == {"own_handler": True, "level": logging.INFO}

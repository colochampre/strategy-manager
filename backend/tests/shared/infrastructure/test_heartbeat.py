"""``HttpHeartbeat`` — the one outbound call that says "still here".

It shares ``TelegramAlerter``'s asymmetric contract and for a sharper reason.
The alerter must not raise because it runs behind work that is already in
trouble; this must not raise because it runs inside the watchdog, which is the
one recurring chain nothing else is watching. A raise here would let an
unreachable monitoring endpoint kill the component whose entire purpose is to
notice that something died.

It must not log an ERROR either, and that is a separate rule from the first.
ERROR is what ``AlertLogBridge`` forwards to a phone, so an ERROR here would
page the owner about the MONITORING being down — the same loop the bridge
excludes the alerter's own namespace to prevent.

No test touches the network: every one goes through ``httpx.MockTransport``.
"""

import logging

import httpx
import pytest

from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.alert_log_bridge import (
    EXCLUDED_LOGGER_PREFIXES,
)
from strategy_manager.shared.infrastructure.heartbeat import (
    HttpHeartbeat,
    build_heartbeat,
)

# Shaped like a healthchecks.io ping URL: an opaque token in the PATH, with no
# query string and no header. That shape is the whole reason this URL is
# treated as a secret.
URL = "https://hc-ping.com/6f1a0c3e-9d52-4c8b-bd77-1f2e3a4b5c6d"
TOKEN = "6f1a0c3e-9d52-4c8b-bd77-1f2e3a4b5c6d"

HEARTBEAT_LOGGER = "strategy_manager.alerts.heartbeat"


class Recorder:
    """A ping receiver that records what it was asked."""

    def __init__(self, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self._status_code = status_code

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code)


class Unreachable:
    def __init__(self, exc: Exception | None = None) -> None:
        self.calls = 0
        self._exc = exc or httpx.ConnectError(f"no route to host for {URL}")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise self._exc


def _heartbeat(handler: object, *, timeout_seconds: float = 4.0) -> HttpHeartbeat:
    return HttpHeartbeat(
        url=URL,
        timeout_seconds=timeout_seconds,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


async def _ping(handler: object) -> None:
    heartbeat = _heartbeat(handler)
    try:
        await heartbeat.ping()
    finally:
        await heartbeat.aclose()


# --- the ping itself -------------------------------------------------------


async def test_a_ping_reaches_the_configured_url() -> None:
    recorder = Recorder()

    await _ping(recorder)

    assert len(recorder.requests) == 1
    assert str(recorder.requests[0].url) == URL


async def test_the_ping_carries_no_body_and_no_query() -> None:
    """Provider-agnostic on purpose: healthchecks.io, Better Stack, Cronitor
    and a hand-rolled cron receiver all accept a bare request to an opaque URL,
    and none of them needs anything in it."""
    recorder = Recorder()

    await _ping(recorder)

    assert recorder.requests[0].content == b""
    assert recorder.requests[0].url.query == b""


async def test_the_configured_timeout_bounds_the_call() -> None:
    heartbeat = _heartbeat(Recorder(), timeout_seconds=1.5)
    try:
        assert heartbeat.timeout_seconds == pytest.approx(1.5)
    finally:
        await heartbeat.aclose()


# --- what it must never do -------------------------------------------------


async def test_an_unreachable_endpoint_does_not_raise() -> None:
    handler = Unreachable()

    await _ping(handler)

    assert handler.calls == 1


async def test_a_timeout_does_not_raise() -> None:
    await _ping(Unreachable(httpx.ReadTimeout("timed out")))


async def test_a_failed_ping_is_a_warning_and_never_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ERROR is the level the alert bridge forwards. A monitoring endpoint that
    is briefly unreachable must not ring a phone about the monitoring."""
    with caplog.at_level(logging.DEBUG, logger=HEARTBEAT_LOGGER):
        await _ping(Unreachable())

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert [r for r in caplog.records if r.levelno == logging.WARNING] != []


async def test_a_refusing_endpoint_is_a_warning_naming_the_status(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=HEARTBEAT_LOGGER):
        await _ping(Recorder(status_code=503))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "503" in warnings[0].getMessage()
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_a_successful_ping_says_nothing_at_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Once every five minutes forever. Anything above DEBUG here is noise that
    teaches its reader to skip the journal."""
    with caplog.at_level(logging.INFO, logger=HEARTBEAT_LOGGER):
        await _ping(Recorder())

    assert caplog.records == []


# --- the URL is a credential -----------------------------------------------


async def test_the_url_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """httpx puts the request URL inside its own exception messages, and the
    whole secret of a ping URL is its path. Anyone holding it can forge the
    heartbeat, which would turn the dead-man's switch off silently."""
    with caplog.at_level(logging.DEBUG, logger=HEARTBEAT_LOGGER):
        await _ping(Unreachable())

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert TOKEN not in logged
    assert URL not in logged


async def test_a_bare_path_in_the_message_is_redacted_too(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Some errors name the path without the scheme and host, so an exact
    whole-URL match alone would let the token through."""
    with caplog.at_level(logging.DEBUG, logger=HEARTBEAT_LOGGER):
        await _ping(Unreachable(httpx.ConnectError(f"failed on /{TOKEN}")))

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert TOKEN not in logged


def test_its_logger_sits_inside_the_namespace_the_bridge_excludes() -> None:
    """Belt and braces with the WARNING level. The bridge drops these records
    before the level is even considered, so a future ERROR added here still
    cannot become an alert about the alerting."""
    assert HEARTBEAT_LOGGER.startswith(EXCLUDED_LOGGER_PREFIXES[0])


# --- composition -----------------------------------------------------------


def test_no_url_means_no_heartbeat() -> None:
    """Empty is off, and off is silent: a deployment that sets nothing behaves
    exactly as it did before this existed."""
    assert build_heartbeat(Settings(watchdog_heartbeat_url="")) is None


def test_a_configured_url_builds_a_heartbeat() -> None:
    heartbeat = build_heartbeat(
        Settings(watchdog_heartbeat_url=URL, watchdog_heartbeat_timeout_seconds=3.0)
    )

    assert heartbeat is not None
    assert heartbeat.timeout_seconds == pytest.approx(3.0)


def test_surrounding_whitespace_in_the_setting_is_not_a_url() -> None:
    """A URL pasted into a ``.env`` with a trailing space would otherwise
    become a request to a host that does not exist, once every five minutes,
    reported only as a WARNING nobody reads."""
    heartbeat = build_heartbeat(Settings(watchdog_heartbeat_url=f"  {URL}  "))

    assert heartbeat is not None
    assert heartbeat.url == URL

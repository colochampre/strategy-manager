"""``TelegramAlerter`` — the one adapter that carries an ERROR to a phone.

Its contract is asymmetric with the rest of this system: every other adapter is
allowed, often required, to fail loudly. This one is not. It runs behind a job
that is already in trouble, so a raise here would turn "the balance sync died"
into "the balance sync died AND the alert about it took the worker's retry
budget with it". A failure to alert is logged and swallowed.

That swallowing is exactly why it is worth testing hard: nothing downstream
would ever notice it going wrong.
"""

import json
import logging

import httpx
import pytest

from strategy_manager.shared.infrastructure.alert_log_bridge import (
    EXCLUDED_LOGGER_PREFIXES,
)
from strategy_manager.shared.infrastructure.telegram_alerter import (
    TELEGRAM_TEXT_LIMIT,
    TelegramAlerter,
)

TOKEN = "8123456789:AAH1z_kQm0pQrStUvWxYz012345678ab"
CHAT_ID = "-1001234567890"


class Recorder:
    """A Bot API that records what it was asked to send."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._response = response or httpx.Response(200, json={"ok": True})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._response

    @property
    def text(self) -> str:
        return str(self.payload["text"])

    @property
    def payload(self) -> dict[str, object]:
        body: dict[str, object] = json.loads(self.requests[0].content)
        return body


class Unreachable:
    """A Bot API that cannot be reached at all."""

    def __init__(self, message: str = "no route to host") -> None:
        self.calls = 0
        self._message = message

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise httpx.ConnectError(self._message)


def _alerter(handler: object, *, timeout_seconds: float = 4.0) -> TelegramAlerter:
    return TelegramAlerter(
        bot_token=TOKEN,
        chat_id=CHAT_ID,
        timeout_seconds=timeout_seconds,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


async def _send(handler: object, title: str, body: str) -> None:
    alerter = _alerter(handler)
    try:
        await alerter.send(title, body)
    finally:
        await alerter.aclose()


async def test_it_posts_the_title_and_body_to_the_bot_api() -> None:
    bot = Recorder()

    await _send(bot, "balance.sync FAILED", "pool bybit/usdt-m/USDT is stale")

    assert len(bot.requests) == 1
    assert bot.requests[0].url.path == f"/bot{TOKEN}/sendMessage"
    assert bot.payload["chat_id"] == CHAT_ID
    assert "balance.sync FAILED" in bot.text
    assert "pool bybit/usdt-m/USDT is stale" in bot.text


async def test_the_message_is_sent_as_plain_text() -> None:
    """No ``parse_mode``, deliberately. A log line is arbitrary text —
    underscores in identifiers, asterisks in a traceback, unbalanced
    backticks — and any markup mode turns some of them into an escape
    sequence that Telegram rejects, or that truncation can cut in half.
    Plain text has no escape syntax, so there is nothing to cut."""
    bot = Recorder()

    await _send(bot, "t", "a_b *c* `d")

    assert "parse_mode" not in bot.payload


async def test_a_transport_failure_is_swallowed() -> None:
    await _send(Unreachable(), "title", "body")


async def test_a_rejection_by_telegram_is_swallowed() -> None:
    """Telegram answers a bad chat_id with HTTP 400 and ``ok: false``. A
    misconfigured channel must not be able to fail a job."""

    rejecting = Recorder(
        httpx.Response(400, json={"ok": False, "description": "chat not found"})
    )

    await _send(rejecting, "title", "body")


async def test_a_failure_is_logged_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    """WARNING, not ERROR, and that is not timidity. ERROR is the level the
    bridge forwards, so an alerter logging at ERROR would be asking itself to
    alert about its own failure to alert."""
    with caplog.at_level(logging.DEBUG):
        await _send(Unreachable(), "title", "body")

    failures = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(failures) == 1
    assert failures[0].levelno == logging.WARNING


async def test_the_bot_token_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """httpx puts the request URL into its own exception messages, and this
    adapter's token IS part of that URL. Logging the exception verbatim would
    publish the alerting credential into the log on every outage."""
    unreachable = Unreachable(
        f"timed out connecting to https://api.telegram.org/bot{TOKEN}/sendMessage"
    )

    with caplog.at_level(logging.DEBUG):
        await _send(unreachable, "title", "body")

    for record in caplog.records:
        assert TOKEN not in record.getMessage()


async def test_the_alert_body_never_carries_a_secret() -> None:
    """The body is log-derived, so it can contain anything the log did."""
    bot = Recorder()

    await _send(bot, "title", f"leaked bot{TOKEN} in a traceback")

    assert TOKEN not in bot.text


async def test_a_long_body_is_truncated_to_telegrams_limit() -> None:
    """Telegram rejects anything over 4096 characters outright, so an
    untruncated alert about a large failure is no alert at all."""
    bot = Recorder()

    await _send(bot, "title", "x" * 10_000)

    assert len(bot.text) <= TELEGRAM_TEXT_LIMIT
    assert bot.text.endswith("[truncated]")
    assert bot.text.startswith("title")


async def test_truncation_keeps_the_text_encodable() -> None:
    """The cut is made on a code-point boundary, never inside a character's
    own encoding — a half character would fail to serialise as JSON."""
    bot = Recorder()

    await _send(bot, "title", "\N{ROCKET}" * 5_000)

    assert bot.text.encode("utf-8").decode("utf-8") == bot.text
    assert len(bot.text) <= TELEGRAM_TEXT_LIMIT


async def test_a_short_message_is_not_truncated() -> None:
    bot = Recorder()

    await _send(bot, "title", "body")

    assert "truncated" not in bot.text


async def test_the_send_timeout_is_explicit() -> None:
    """An alert that blocks on a socket is worse than no alert: it holds the
    drain task, and every later ERROR queues behind it."""
    alerter = _alerter(Recorder(), timeout_seconds=2.5)
    try:
        assert alerter.timeout_seconds == 2.5
    finally:
        await alerter.aclose()


def test_the_alerters_logger_sits_inside_the_bridges_excluded_namespace() -> None:
    """The recursion guard depends on this and cannot assert it at runtime:
    the bridge excludes a namespace and this adapter has to be inside it. An
    import would couple the adapter to the bridge, so the invariant is pinned
    here instead."""

    from strategy_manager.shared.infrastructure import telegram_alerter

    assert telegram_alerter.logger.name.startswith(EXCLUDED_LOGGER_PREFIXES[0])

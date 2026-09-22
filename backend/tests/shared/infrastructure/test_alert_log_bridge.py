"""``AlertLogBridge`` — the thing that makes an ERROR reachable.

The defect it exists for: ``balance.sync`` was dead for three days in
production. The journal held a warning every retry and nobody read it, so the
deployment stopped learning its own capital while looking alive.

A logging handler is a hostile place to put an outbound HTTP call, and every
test below is one of the ways it would otherwise go wrong:

  RECURSION   The alerter fails, that failure is logged, the log triggers an
              alert, which fails. One ERROR becomes an unbounded loop of them.
  BLOCKING    ``emit`` is called from whatever thread is logging, inside the
              caller's own stack. Awaiting an HTTP round trip there stalls the
              event loop; doing it under a lock deadlocks it.
  FLOODING    A retrying job logs the same ERROR every attempt. Unthrottled,
              one broken chain empties the phone's battery and trains its
              owner to swipe alerts away.
  LEAKING     The body is assembled from log records, which carry signed URLs
              and, once, a database DSN.
"""

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta

import pytest

from strategy_manager.shared.infrastructure.alert_log_bridge import (
    EXCLUDED_LOGGER_PREFIXES,
    AlertLogBridge,
)

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
WINDOW = 900.0

SOURCE = "strategy_manager.accounts.balance_sync"


class MovableClock:
    def __init__(self) -> None:
        self._now = NOW

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


class SpyAlerter:
    def __init__(self, raises: Exception | None = None) -> None:
        self.sent: list[tuple[str, str]] = []
        self._raises = raises

    async def send(self, title: str, body: str) -> None:
        self.sent.append((title, body))
        if self._raises is not None:
            raise self._raises


class BlockingAlerter:
    """An alerter whose send never returns until it is released — a slow
    Telegram, which is the only way the queue ever actually fills."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._gate = asyncio.Event()

    async def send(self, title: str, body: str) -> None:
        self.sent.append((title, body))
        await self._gate.wait()

    def release(self) -> None:
        self._gate.set()


def _record(
    message: str,
    *,
    name: str = SOURCE,
    level: int = logging.ERROR,
    args: object = (),
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name, level=level, pathname=__file__, lineno=1, msg=message, args=args,
        exc_info=None,
    )


async def _bridge(
    alerter: SpyAlerter | BlockingAlerter,
    clock: MovableClock | None = None,
    *,
    capacity: int = 64,
    deployment: str = "test-host",
) -> AlertLogBridge:
    bridge = AlertLogBridge(
        alerter,
        clock=clock or MovableClock(),
        throttle_window_seconds=WINDOW,
        capacity=capacity,
        deployment=deployment,
    )
    await bridge.start()
    return bridge


async def test_the_body_opens_with_the_source_and_the_time() -> None:
    """An alert read on a phone has to answer WHERE and WHEN before anything
    else. Production and a developer's machine write to the same chat, so an
    alert that does not name its source cannot be told from a rehearsal."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter, deployment="prod-vps")

    bridge.emit(_record("something broke"))
    await bridge.drain()
    await bridge.aclose()

    first_line = alerter.sent[0][1].splitlines()[0]
    assert "prod-vps" in first_line
    assert "UTC" in first_line


async def test_the_body_does_not_repeat_the_title() -> None:
    """The title already carries the level and the logger. Repeating them as
    the body's first line spends the two lines a phone notification shows on
    nothing."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("the actual message"))
    await bridge.drain()
    await bridge.aclose()

    title, body = alerter.sent[0]
    assert title == f"ERROR in {SOURCE}"
    assert "the actual message" in body
    assert SOURCE not in body
    assert "ERROR" not in body


async def test_an_error_is_forwarded_to_the_alerter() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("balance.sync failed after 5 attempts"))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1
    title, body = alerter.sent[0]
    assert "balance.sync failed after 5 attempts" in body
    # The logger lives in the TITLE, not the body: repeating it there spent
    # one of the two lines a phone notification shows.
    assert SOURCE in title


async def test_the_title_names_the_level_and_the_logger() -> None:
    """An alert read on a phone at 3am has to say what it is before it says
    anything else."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("boom", level=logging.CRITICAL))
    await bridge.drain()
    await bridge.aclose()

    assert "CRITICAL" in alerter.sent[0][0]


async def test_a_warning_is_not_forwarded() -> None:
    """ERROR is the threshold. A WARNING is a thing worth reading later; an
    ERROR is a thing worth waking someone for, and blurring the two is how a
    channel stops being read at all."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("a retry", level=logging.WARNING))
    bridge.emit(_record("some detail", level=logging.INFO))
    await bridge.drain()
    await bridge.aclose()

    assert alerter.sent == []


async def test_a_critical_is_forwarded() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("the process is going down", level=logging.CRITICAL))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1


# --- recursion -----------------------------------------------------------


async def test_an_error_from_the_alerters_own_namespace_is_ignored() -> None:
    """The loop this prevents: the alerter cannot reach Telegram, logs that,
    the bridge forwards it, the alerter cannot reach Telegram..."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("could not deliver", name=f"{EXCLUDED_LOGGER_PREFIXES[0]}.telegram"))
    await bridge.drain()
    await bridge.aclose()

    assert alerter.sent == []


@pytest.mark.parametrize("library", ["httpx", "httpcore"])
async def test_an_error_from_the_http_stack_underneath_the_alerter_is_ignored(
    library: str,
) -> None:
    """The alerter's own HTTP client logs under these names, so an alert that
    fails at the socket would otherwise re-enter through the library rather
    than through the adapter."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("connection reset", name=f"{library}._client"))
    await bridge.drain()
    await bridge.aclose()

    assert alerter.sent == []


async def test_a_failing_transport_produces_exactly_one_send_attempt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The end-to-end recursion proof, with the REAL adapter: make the
    transport raise, and count. Exactly one attempt, and the second ERROR
    never happens."""
    import httpx

    from strategy_manager.shared.infrastructure.telegram_alerter import TelegramAlerter

    attempts = 0

    def unreachable(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("no route to host")

    alerter = TelegramAlerter(
        bot_token="8123456789:AAH1z_kQm0pQrStUvWxYz012345678ab",
        chat_id="-100",
        timeout_seconds=1.0,
        transport=httpx.MockTransport(unreachable),
    )
    bridge = AlertLogBridge(
        alerter,
        clock=MovableClock(),
        throttle_window_seconds=WINDOW,
        deployment="test-host",
    )
    await bridge.start()

    # Installed on the root logger, exactly as the entry points install it, so
    # anything the alerter logs on its way down really does come back here.
    root = logging.getLogger()
    root.addHandler(bridge)
    try:
        with caplog.at_level(logging.DEBUG):
            logging.getLogger(SOURCE).error("balance.sync failed after 5 attempts")
            await bridge.drain()
            # A second drain: if the alerter's own failure had re-entered, the
            # queue would have grown while the first drain was running.
            await bridge.drain()
    finally:
        root.removeHandler(bridge)
        await bridge.aclose()
        await alerter.aclose()

    assert attempts == 1


async def test_an_error_raised_by_the_alerter_does_not_kill_the_drain_task() -> None:
    """An ``AlertPort`` other than ours may raise. One bad send must not end
    the bridge for the rest of the process's life."""
    alerter = SpyAlerter(raises=RuntimeError("boom"))
    bridge = await _bridge(alerter)

    bridge.emit(_record("first"))
    await bridge.drain()
    bridge.emit(_record("second"))
    await bridge.drain()
    await bridge.aclose()

    assert [body for _, body in alerter.sent] != []
    assert len(alerter.sent) == 2


# --- never blocking ------------------------------------------------------


async def test_emit_returns_before_the_alert_is_sent() -> None:
    """``emit`` runs inside the caller's own stack, on whatever thread was
    logging. The send happens later, on the drain task."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("boom"))
    assert alerter.sent == []

    await bridge.drain()
    await bridge.aclose()
    assert len(alerter.sent) == 1


def test_emit_without_a_running_loop_drops_and_counts() -> None:
    """A record logged from a thread with no event loop — or before the
    bridge was started, or after the loop closed — must be dropped, not
    raised. Raising inside ``emit`` would make logging itself a failure
    mode."""
    alerter = SpyAlerter()
    bridge = AlertLogBridge(
        alerter,
        clock=MovableClock(),
        throttle_window_seconds=WINDOW,
        deployment="test-host",
    )

    bridge.emit(_record("nobody is listening"))

    assert alerter.sent == []
    assert bridge.dropped == 1


async def test_emit_from_another_thread_reaches_the_drain_task() -> None:
    """The normal case for a worker that ever logs off the loop thread."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    thread = threading.Thread(target=lambda: bridge.emit(_record("from a thread")))
    thread.start()
    thread.join()

    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1


async def test_a_full_queue_drops_and_counts_rather_than_blocking() -> None:
    """Back-pressure onto the logging call is not an option: it would stall
    whatever was logging, which is the worker. The ALERT is what gets dropped,
    and the drop is counted so a lossy channel is distinguishable from a
    silent one."""
    alerter = BlockingAlerter()
    bridge = await _bridge(alerter, capacity=2)

    # Distinct templates, or the throttle would collapse them to one key and
    # the queue would never fill.
    for i in range(20):
        bridge.emit(_record(f"failure number {i}"))
    await bridge.drain_scheduled()

    assert bridge.dropped >= 1

    alerter.release()
    await bridge.aclose()


# --- throttling ----------------------------------------------------------


async def test_the_second_alert_for_the_same_key_inside_the_window_is_suppressed() -> None:
    """A failing job retries five times and logs the same ERROR each time."""
    alerter = SpyAlerter()
    clock = MovableClock()
    bridge = await _bridge(alerter, clock)

    bridge.emit(_record("balance.sync failed"))
    bridge.emit(_record("balance.sync failed"))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1


async def test_the_key_is_the_template_not_the_formatted_message() -> None:
    """Otherwise ``"attempt %d failed"`` is a different key every attempt and
    the throttle never fires."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("attempt %d failed", args=(1,)))
    bridge.emit(_record("attempt %d failed", args=(2,)))
    bridge.emit(_record("attempt %d failed", args=(3,)))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1
    assert "attempt 1 failed" in alerter.sent[0][1]


async def test_the_same_message_from_a_different_logger_is_its_own_key() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("failed", name="strategy_manager.a"))
    bridge.emit(_record("failed", name="strategy_manager.b"))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 2


async def test_the_next_alert_names_how_many_were_suppressed() -> None:
    """The count is the whole point: "it happened again" and "it happened 34
    more times" are different incidents."""
    alerter = SpyAlerter()
    clock = MovableClock()
    bridge = await _bridge(alerter, clock)

    bridge.emit(_record("balance.sync failed"))
    for _ in range(34):
        bridge.emit(_record("balance.sync failed"))
    await bridge.drain()

    clock.advance(WINDOW + 1)
    bridge.emit(_record("balance.sync failed"))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 2
    assert "+34 suppressed" in alerter.sent[1][1]


async def test_an_alert_after_the_window_with_nothing_suppressed_says_nothing() -> None:
    alerter = SpyAlerter()
    clock = MovableClock()
    bridge = await _bridge(alerter, clock)

    bridge.emit(_record("balance.sync failed"))
    await bridge.drain()
    clock.advance(WINDOW + 1)
    bridge.emit(_record("balance.sync failed"))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 2
    assert "suppressed" not in alerter.sent[1][1]


async def test_the_suppressed_count_resets_after_it_is_reported() -> None:
    alerter = SpyAlerter()
    clock = MovableClock()
    bridge = await _bridge(alerter, clock)

    bridge.emit(_record("failed"))
    bridge.emit(_record("failed"))
    clock.advance(WINDOW + 1)
    bridge.emit(_record("failed"))
    clock.advance(WINDOW + 1)
    bridge.emit(_record("failed"))
    await bridge.drain()
    await bridge.aclose()

    assert "+1 suppressed" in alerter.sent[1][1]
    assert "suppressed" not in alerter.sent[2][1]


# --- redaction -----------------------------------------------------------


async def test_the_body_is_redacted_before_it_leaves() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(
        _record(
            "read failed: GET https://api.bybit.com/v5/account/wallet-balance"
            "?api_key=AAAABBBB&sign=deadbeef"
        )
    )
    await bridge.drain()
    await bridge.aclose()

    body = alerter.sent[0][1]
    assert "AAAABBBB" not in body
    assert "deadbeef" not in body
    assert "api.bybit.com" in body


async def test_a_traceback_is_carried_and_redacted() -> None:
    """The DSN this rule exists for arrived in a traceback, not in a message."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    try:
        raise ValueError(
            "postgresql+asyncpg://postgres:hunter2@localhost:5432/strategy_manager"
        )
    except ValueError:
        import sys

        record = _record("connection failed")
        record.exc_info = sys.exc_info()
        bridge.emit(record)

    await bridge.drain()
    await bridge.aclose()

    body = alerter.sent[0][1]
    assert "hunter2" not in body
    assert "ValueError" in body


# --- lifecycle -----------------------------------------------------------


async def test_closing_stops_the_drain_task() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    await bridge.aclose()

    assert bridge.closed


async def test_closing_twice_is_harmless() -> None:
    bridge = await _bridge(SpyAlerter())

    await bridge.aclose()
    await bridge.aclose()


async def test_emit_after_close_drops_rather_than_raising() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)
    await bridge.aclose()

    bridge.emit(_record("too late"))

    assert alerter.sent == []


async def test_a_pending_alert_is_still_sent_before_the_bridge_closes() -> None:
    """Shutdown is exactly when the interesting ERROR is logged."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("the worker is stopping because of this"))
    await bridge.aclose()

    assert len(alerter.sent) == 1


async def test_starting_twice_leaves_one_drain_task() -> None:
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    await bridge.start()
    bridge.emit(_record("boom"))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1


async def test_the_handler_level_keeps_cheap_records_out_of_emit() -> None:
    """``logging`` skips a handler whose level is above the record's without
    ever calling ``emit``, so the DEBUG traffic of a busy worker costs a
    comparison rather than a formatted record."""
    bridge = await _bridge(SpyAlerter())

    assert bridge.level == logging.ERROR

    await bridge.aclose()


def test_the_excluded_prefixes_name_the_alerting_namespace_first() -> None:
    assert EXCLUDED_LOGGER_PREFIXES[0] == "strategy_manager.alerts"
    assert "httpx" in EXCLUDED_LOGGER_PREFIXES
    assert "httpcore" in EXCLUDED_LOGGER_PREFIXES


async def test_a_reentrant_emit_from_inside_emit_is_refused() -> None:
    """The guard of last resort. Even if a namespace were missed, something
    logging an ERROR from inside this handler's own ``emit`` must not be
    allowed to start a second pass."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)
    seen: list[int] = []

    original = bridge.deliver

    def reentrant(record: logging.LogRecord) -> None:
        seen.append(1)
        if len(seen) == 1:
            bridge.emit(_record("from inside emit", name="totally.unexcluded"))
        original(record)

    bridge.deliver = reentrant  # type: ignore[method-assign]
    bridge.emit(_record("outer"))
    await bridge.drain()
    await bridge.aclose()

    assert len(seen) == 1
    assert len(alerter.sent) == 1


async def test_asyncio_errors_are_not_forwarded() -> None:
    """asyncio logs "Task exception was never retrieved" at ERROR from inside
    the loop the drain task runs on. Forwarding it would let a failure in the
    drain task itself feed the queue it drains."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("Task exception was never retrieved", name="asyncio"))
    await bridge.drain()
    await bridge.aclose()

    assert alerter.sent == []


async def test_an_unformattable_record_still_produces_an_alert() -> None:
    """A broken format string is a bug in the caller, not a reason to lose the
    alert — and certainly not a reason for the alerting path to raise inside
    someone else's logging call. The raw template still names what failed."""
    alerter = SpyAlerter()
    bridge = await _bridge(alerter)

    bridge.emit(_record("%d and %d", args=(1,)))
    await bridge.drain()
    await bridge.aclose()

    assert len(alerter.sent) == 1
    assert "%d and %d" in alerter.sent[0][1]

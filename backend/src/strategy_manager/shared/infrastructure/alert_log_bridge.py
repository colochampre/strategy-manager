"""Carries an ERROR out of the log and into a channel someone actually reads.

The defect this exists for: ``balance.sync`` was dead for three days in
production. Every retry wrote a warning to the journal, the chain exhausted
its attempts, and nothing else happened — the deployment stopped learning its
own capital while looking alive, because the log was the only signal and
nobody reads a log that is quiet 99% of the time.

A ``logging.Handler`` is a hostile place to put an outbound HTTP call, so
almost all of this file is about what it must NOT do:

**Never recurse.** The alerter fails; that failure is logged; the log is
forwarded; the alerter fails. One unreachable phone becomes an unbounded loop.
Two guards, because one is not enough: the alerting namespace and the HTTP
stack underneath it are excluded by logger name, and a re-entrancy flag
refuses a second pass through ``emit`` on the same thread regardless.

**Never block.** ``emit`` is synchronous and runs inside the caller's stack, on
whatever thread was logging. It formats, throttles and hands the result to a
queue; one background task drains it. Nothing here awaits I/O, takes a lock a
send could be holding, or applies back-pressure to the logging call — when the
queue is full, or no loop is running to hand it to, the ALERT is dropped and
counted. Losing an alert is bad; stalling the worker that logged it is worse.

**Never flood.** One alert per (logger, message template) per window. A failing
job logs the same ERROR on every attempt, and an unthrottled channel trains
its owner to swipe alerts away — which is the original defect again, with an
extra step.

**Never leak.** The body is assembled out of log records, which in this system
have carried a signed venue URL and, once, a database DSN. Everything is
passed through ``redact`` on the way out.
"""

import asyncio
import logging
import threading
from collections.abc import Hashable
from contextlib import suppress
from datetime import datetime

from strategy_manager.shared.application.ports import AlertPort, ClockPort
from strategy_manager.shared.infrastructure.alert_redaction import redact

# The namespace every alerting component logs under, plus the HTTP stack the
# alerter's own client logs through, plus asyncio — which logs "Task exception
# was never retrieved" at ERROR from inside the very loop the drain task runs
# on. A record from any of these is dropped before anything else happens to
# it: forwarding one is how a failure to alert becomes a loop of failures to
# alert. The alerting namespace is first because adapters are required to sit
# inside it (see ``telegram_alerter``).
EXCLUDED_LOGGER_PREFIXES: tuple[str, ...] = (
    "strategy_manager.alerts",
    "httpx",
    "httpcore",
    "anyio",
    "asyncio",
)

DEFAULT_CAPACITY = 256

_ThrottleKey = tuple[str, Hashable]


class _Throttle:
    """One admission per key per window, counting what it turned away.

    The count is not bookkeeping: "it happened again" and "it happened 34 more
    times" are different incidents, and the second one is the one that says a
    chain is dead rather than flaky.
    """

    def __init__(self, window_seconds: float, clock: ClockPort) -> None:
        self._window = window_seconds
        self._clock = clock
        self._last: dict[_ThrottleKey, datetime] = {}
        self._suppressed: dict[_ThrottleKey, int] = {}

    def admit(self, key: _ThrottleKey) -> int | None:
        """``None`` when this one is suppressed; otherwise how many were
        suppressed since the previous admission of the same key."""
        now = self._clock.now()
        last = self._last.get(key)
        if last is not None and (now - last).total_seconds() < self._window:
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
            return None
        self._last[key] = now
        return self._suppressed.pop(key, 0)


def describe_window(seconds: float) -> str:
    """The window as an operator would say it, for the suppression note."""
    if seconds >= 3600:
        return f"{seconds / 3600:g} h"
    if seconds >= 60:
        return f"{seconds / 60:g} min"
    return f"{seconds:g} s"


class AlertLogBridge(logging.Handler):
    """Forwards ERROR and above to an ``AlertPort``, off the logging thread."""

    def __init__(
        self,
        alerter: AlertPort,
        *,
        clock: ClockPort,
        throttle_window_seconds: float,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        # The handler's own level, so ``logging`` skips this handler on a DEBUG
        # record without ever building one — the busy path costs a comparison.
        super().__init__(level=logging.ERROR)
        self._alerter = alerter
        self._throttle = _Throttle(throttle_window_seconds, clock)
        self._window_seconds = throttle_window_seconds
        self._capacity = capacity
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=capacity)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._reentrant = threading.local()
        self._state = threading.Lock()
        self._dropped = 0
        # Hand-offs accepted by ``emit`` but not yet enqueued by the loop.
        self._in_flight = 0

    # --- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        """Binds the bridge to the running loop and starts the one drain task.

        Idempotent: both entry points compose more than once in a test
        session, and a second drain task would double every alert.
        """
        if self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._task = asyncio.create_task(self._drain_forever(), name="alert-bridge")

    async def drain(self) -> None:
        """Waits until everything ``emit`` has accepted has reached the alerter.

        Two waits, because there are two hand-offs. ``emit`` only SCHEDULES
        the enqueue — it may be running on another thread and cannot touch the
        queue directly — so joining the queue first would see it empty and
        return before a single alert had been queued at all.
        """
        await self.drain_scheduled()
        await self._queue.join()

    async def drain_scheduled(self) -> None:
        """Waits only for the first hand-off: everything ``emit`` accepted has
        either reached the queue or been counted as a drop."""
        while self._in_flight > 0:
            await asyncio.sleep(0)

    async def aclose(self) -> None:
        """Delivers what is already queued, then stops.

        The pending alerts are flushed FIRST, deliberately: shutdown is
        precisely when the ERROR worth reading gets logged.
        """
        if self._closed:
            return
        if self._task is not None:
            await self.drain()
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._closed = True
        self._loop = None

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def throttle_window_seconds(self) -> float:
        return self._window_seconds

    @property
    def dropped(self) -> int:
        """Alerts thrown away because nothing could carry them.

        Read by the operator script and worth watching: a non-zero value means
        the channel is lossy, which is a different problem from the channel
        being silent.
        """
        return self._dropped

    # --- the logging side (any thread, inside the caller's stack) ---------

    def emit(self, record: logging.LogRecord) -> None:
        """Never raises, never blocks, never re-enters.

        ``logging`` calls this from whatever thread logged. Everything past
        the guards is pure formatting plus a queue hand-off.
        """
        if record.levelno < logging.ERROR or self._closed:
            return
        if record.name.startswith(EXCLUDED_LOGGER_PREFIXES):
            return
        if getattr(self._reentrant, "active", False):
            return

        self._reentrant.active = True
        try:
            self.deliver(record)
        except Exception:  # pragma: no cover - the last resort, by definition
            # A handler that raises makes logging itself a failure mode, and
            # the caller was already reporting an error when it got here.
            self._count_drop()
        finally:
            self._reentrant.active = False

    def deliver(self, record: logging.LogRecord) -> None:
        """Throttle, render, hand off. Separated from ``emit`` so the guards
        above cannot be bypassed by a subclass overriding the work."""
        key: _ThrottleKey = (record.name, _template_of(record))
        with self._state:
            suppressed = self._throttle.admit(key)
        if suppressed is None:
            return

        self._offer_threadsafe(_title(record), _body(record, suppressed, self._window_seconds))

    def _offer_threadsafe(self, title: str, body: str) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            # No loop was ever bound, the bridge is not started, or the loop
            # has gone. Dropping is the only option that is not a raise inside
            # somebody else's logging call.
            self._count_drop()
            return
        if self._queue.qsize() >= self._capacity:
            self._count_drop()
            return
        with self._state:
            self._in_flight += 1
        try:
            loop.call_soon_threadsafe(self._offer, title, body)
        except RuntimeError:
            with self._state:
                self._in_flight -= 1
            self._count_drop()

    def _offer(self, title: str, body: str) -> None:
        """Runs on the loop thread; the only place anything is queued."""
        try:
            self._queue.put_nowait((title, body))
        except asyncio.QueueFull:
            self._count_drop()
        finally:
            with self._state:
                self._in_flight -= 1

    def _count_drop(self) -> None:
        with self._state:
            self._dropped += 1

    # --- the sending side (one task, on the loop) ------------------------

    async def _drain_forever(self) -> None:
        while True:
            title, body = await self._queue.get()
            try:
                await self._alerter.send(title, body)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception:
                # An ``AlertPort`` other than ours may raise. One bad send
                # must not end alerting for the life of the process — and it
                # must not be logged from here at a level this bridge would
                # forward, which is why the alerter owns its own reporting.
                pass
            self._queue.task_done()


def _template_of(record: logging.LogRecord) -> Hashable:
    """The message TEMPLATE, not the formatted message.

    ``"attempt %d failed"`` must be one throttle key, or every retry is a
    fresh key and the throttle never fires on the one thing it is for.
    """
    return record.msg if isinstance(record.msg, Hashable) else str(record.msg)


def _title(record: logging.LogRecord) -> str:
    return f"{record.levelname} in {record.name}"


def _body(record: logging.LogRecord, suppressed: int, window_seconds: float) -> str:
    lines = [f"{record.levelname} {record.name}", "", _message_of(record)]

    if record.exc_info is not None:
        lines += ["", logging.Formatter().formatException(record.exc_info)]

    if suppressed:
        lines += [
            "",
            f"+{suppressed} suppressed (throttled to 1 per "
            f"{describe_window(window_seconds)})",
        ]

    return redact("\n".join(lines))


def _message_of(record: logging.LogRecord) -> str:
    """A broken format string is the caller's bug, not a reason to lose the
    alert: the raw template still names what failed."""
    try:
        return record.getMessage()
    except Exception:
        return str(record.msg)

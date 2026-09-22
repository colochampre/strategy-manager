"""``OpenAfterClose``: the S5 continuation (design.md § S5) that opens a
signal's position only once every close it awaits has settled FILLED,
polling the DATABASE on its own cadence rather than relying on the queue's
failure backoff.

**Why not reuse ``fail()`` backoff** (design.md § S5): the backoff's own
arithmetic (30/60/120/240/480s) means the first recheck alone lands well
after a fill that usually settles in a couple of seconds, and its fifth
retry (930s) already outlasts ``delayed_open_max_signal_age_seconds``
(600s) -- so waiting this way would eventually be recorded as a chain of
failed attempts, and could exhaust into a silent FAILED job with none of
the WARNING/ERROR visibility this continuation gives instead. Real
exceptions still use ``fail()`` -- this class never raises out of ``poll()``.

**Who seeds it**: today, only the rewired Existing-Position Guard
(``HoldingGuard``'s in-flight branch, design.md § S5 amending S2) --
``ProcessSignalHandler._handle_consumes`` calls ``seed()`` when the guard
defers rather than proceeds or refuses. A later unit (S5b, S6) seeds it too,
atomically with a close it is about to place, on the SAME session, BEFORE
that close's own commit -- ``seed()`` itself never commits, mirroring
``enqueue_unique``'s own contract.

**Neither this module nor ``process_signal.py`` imports the other's
class.** ``ProcessSignalHandler`` calls ``seed()`` through a narrow
Protocol it declares itself; this module calls back into
``ProcessSignalHandler.open_now`` through the plain ``OpenNow`` callable
below. Building both together (``main.py``) resolves the two-way reference
with an ordinary closure -- neither constructor needs the other to exist
yet.

**Poll threading (orchestrator-found defect, fixed same commit)**: a
chain step that re-defers must seed the NEXT poll, never restart at poll
0. ``open_now`` re-runs the guard, and the guard can defer AGAIN --
either because the originally awaited close(s) filled but SOME OTHER
work is now in flight, or because the vacuous empty-``awaited_allocation
_ids`` case re-checks the whole guard every time. If that re-defer seeded
poll 0 again, its ``dedupe_key`` would collide with the ALREADY-DONE poll
0 row (``enqueue_unique`` purges DONE rows only after 7 days), the insert
would silently no-op, and the chain would die with nothing left
scheduled and nothing logged -- exactly the failure this continuation
exists to prevent. ``OpenNow`` therefore carries the poll number the
continuation has already reached, and ``ProcessSignalHandler.open_now``
threads it through so a re-defer seeds ``poll + 1``.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort
from strategy_manager.signals.domain.signal import WebhookSignal

logger = logging.getLogger(__name__)

OpenNow = Callable[[UUID, int], Awaitable[object]]
"""``ProcessSignalHandler.open_now`` bound as a plain async callable -- see
this module's docstring for why it is not a Protocol naming that class.
The ``int`` is the poll number THIS invocation was reached from, so a
re-defer inside ``open_now`` knows to seed ``poll + 1`` rather than 0."""


class SignalLookupPort(Protocol):
    """The narrow slice of ``SignalRepositoryPort`` this continuation reads:
    the originating signal (to bound its own age and to detect supersession)
    -- never a write."""

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None: ...

    async def has_newer(
        self, strategy_id: UUID, symbol: str, received_at: datetime
    ) -> bool: ...


class ClosingAttemptsPort(Protocol):
    """The narrow slice of ``SqlAlchemyExecutionAttemptRepository`` this
    continuation reads: one allocation's most recent closing attempt."""

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None: ...


def _dedupe_key(signal_id: UUID, poll: int) -> str:
    return f"signal.open_after_close:{signal_id}:{poll}"


def _settling_too_long(
    close: ExecutionAttempt | None, now: datetime, settle_timeout_seconds: float
) -> bool:
    """Whether an existing-but-unresolved close has been SUBMITTED longer
    than ``open_after_close_settle_timeout_seconds``. ``None`` (no closing
    attempt exists at all yet) never times out on its own -- only the
    signal's own overall age bound governs that case."""
    if close is None or close.created_at is None:
        return False
    return (now - close.created_at).total_seconds() > settle_timeout_seconds


class OpenAfterClose:
    def __init__(
        self,
        signals: SignalLookupPort,
        attempts: ClosingAttemptsPort,
        queue: JobQueuePort,
        clock: ClockPort,
        open_now: OpenNow,
        settle_timeout_seconds: float,
        poll_interval_seconds: float,
        max_signal_age_seconds: float,
    ) -> None:
        self._signals = signals
        self._attempts = attempts
        self._queue = queue
        self._clock = clock
        self._open_now = open_now
        self._settle_timeout_seconds = settle_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._max_signal_age_seconds = max_signal_age_seconds

    async def seed(
        self, signal_id: UUID, awaited_allocation_ids: list[UUID], poll: int = 0
    ) -> None:
        """Enqueues the next poll. NEVER commits (mirrors
        ``JobQueuePort.enqueue_unique`` itself) -- the caller's own
        transaction is what makes the seed durable, atomically with
        whatever write prompted it (design.md § S5).

        Every caller is expected to pass a ``poll`` that has never been
        seeded before for this ``signal_id`` -- a conflict here means some
        caller re-seeded an ALREADY-DONE step instead of advancing the
        chain, which would otherwise silently drop the continuation on the
        floor (``enqueue_unique``'s insert-or-return-existing no-ops rather
        than raising). Logged loudly rather than left to be discovered by
        a signal that never opened."""
        dedupe_key = _dedupe_key(signal_id, poll)
        run_after = self._clock.now() + timedelta(seconds=self._poll_interval_seconds)
        _, inserted = await self._queue.enqueue_unique(
            Job(
                kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
                payload={
                    "signal_id": str(signal_id),
                    "awaited_allocation_ids": [str(a) for a in awaited_allocation_ids],
                    "poll": poll,
                },
                run_after=run_after,
                dedupe_key=dedupe_key,
            )
        )
        if not inserted:
            logger.error(
                "seed conflict for signal %s at poll %s (dedupe_key=%s): a step "
                "already seeded was re-seeded instead of the chain advancing; "
                "the continuation may be stuck",
                signal_id,
                poll,
                dedupe_key,
            )

    async def poll(self, job: ClaimedJob) -> None:
        """The ``signal.open_after_close`` job handler: reads the DATABASE
        ONLY, never the venue, in the exact precedence design.md § S5
        specifies. Every branch either abandons (logging and returning,
        never raising) or reschedules itself -- ``WorkerRunner`` always sees
        this job succeed, because waiting is not a failure."""
        signal_id = UUID(str(job.payload["signal_id"]))
        awaited_allocation_ids = [UUID(str(a)) for a in job.payload["awaited_allocation_ids"]]
        poll = int(job.payload["poll"])

        signal = await self._signals.get_by_id(signal_id)
        if signal is None or signal.received_at is None:
            logger.error(
                "abandoning continuation for signal %s: the signal no longer exists",
                signal_id,
            )
            return

        # (1) A newer signal for the same strategy AND symbol supersedes this
        # one (owner decision A3) -- executing it would act on an intention
        # TradingView has already replaced.
        if await self._signals.has_newer(signal.strategy_id, signal.symbol, signal.received_at):
            logger.warning(
                "abandoning continuation for signal %s: a newer signal for "
                "strategy %s on %s has arrived",
                signal_id,
                signal.strategy_id,
                signal.symbol,
            )
            return

        closes = [await self._attempts.latest_close_for(a) for a in awaited_allocation_ids]

        # (2) Any awaited close that was definitively rejected ends this
        # continuation -- there is nothing left to wait for.
        if any(close is not None and close.status is ExecutionStatus.FAILED for close in closes):
            logger.error(
                "abandoning continuation for signal %s: an awaited close failed",
                signal_id,
            )
            return

        now = self._clock.now()
        signal_age_seconds = (now - signal.received_at).total_seconds()
        # Vacuously True when ``awaited_allocation_ids`` is empty -- the
        # in-flight branch's own defer case, which awaits nothing specific
        # and instead re-checks the whole guard from scratch every poll.
        all_filled = all(
            close is not None and close.status is ExecutionStatus.FILLED for close in closes
        )

        # (3) Every awaited close has settled.
        if all_filled:
            if signal_age_seconds > self._max_signal_age_seconds:
                logger.warning(
                    "abandoning continuation for signal %s: %.0fs old, past the "
                    "%.0fs bound",
                    signal_id,
                    signal_age_seconds,
                    self._max_signal_age_seconds,
                )
                return
            await self._open_now(signal_id, poll)
            return

        # (4) Still waiting -- abandon only past a hard bound, never on
        # ordinary latency.
        timed_out = signal_age_seconds > self._max_signal_age_seconds or any(
            _settling_too_long(close, now, self._settle_timeout_seconds) for close in closes
        )
        if timed_out:
            logger.error(
                "abandoning continuation for signal %s: an awaited close has not "
                "settled within %.0fs",
                signal_id,
                self._settle_timeout_seconds,
            )
            return

        await self.seed(signal_id, awaited_allocation_ids, poll=poll + 1)

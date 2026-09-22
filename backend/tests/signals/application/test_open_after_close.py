"""Unit tests: ``OpenAfterClose``'s poll precedence (design.md § S5; spec:
job-queue § Continuation Scheduling, § Continuation Abandonment, §
Continuation Idempotency).

Fakes only -- no database, no real job queue. The exact SQL each read backs
is proven in ``tests/execution/infrastructure/test_repository.py``
(``latest_close_for``) and ``tests/signals/infrastructure/test_repository.py``
(``has_newer``). This file exercises only ``OpenAfterClose``'s OWN
precedence and scheduling: which branch fires, in what order, and what it
enqueues or calls next.

**Waiting is not a failure**: every branch here either abandons (logs and
returns) or reschedules (``enqueue_unique``) -- ``poll()`` never raises, so
``WorkerRunner`` always acks this job.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.signals.application.open_after_close import OpenAfterClose
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=UTC)
SETTLE_TIMEOUT_SECONDS = 300.0
POLL_INTERVAL_SECONDS = 5.0
MAX_SIGNAL_AGE_SECONDS = 600.0


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


@dataclass
class FakeSignalLookupPort:
    signal: WebhookSignal | None
    newer: bool = False
    has_newer_calls: list[tuple[UUID, str, datetime]] = field(default_factory=list)

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None:
        return self.signal

    async def has_newer(
        self, strategy_id: UUID, symbol: str, received_at: datetime
    ) -> bool:
        self.has_newer_calls.append((strategy_id, symbol, received_at))
        return self.newer


@dataclass
class FakeClosingAttemptsPort:
    closes: dict[UUID, ExecutionAttempt | None] = field(default_factory=dict)
    calls: list[UUID] = field(default_factory=list)

    async def latest_close_for(self, allocation_id: UUID) -> ExecutionAttempt | None:
        self.calls.append(allocation_id)
        return self.closes.get(allocation_id)


@dataclass
class SpyJobQueue:
    """Simulates ``PostgresJobQueue.enqueue_unique``'s real conflict
    behaviour: the SAME ``dedupe_key`` seeded twice returns the FIRST id
    and ``inserted=False`` on the second call, exactly like the real
    ``ON CONFLICT (dedupe_key) DO NOTHING`` -- what lets the poll-threading
    tests below prove a genuine conflict (not a stubbed one)."""

    enqueued: list[Job] = field(default_factory=list)
    ids_by_key: dict[str | None, UUID] = field(default_factory=dict)

    async def enqueue(self, job: Job) -> UUID:
        raise AssertionError("OpenAfterClose must only ever call enqueue_unique")

    async def enqueue_unique(self, job: Job) -> tuple[UUID, bool]:
        self.enqueued.append(job)
        existing = self.ids_by_key.get(job.dedupe_key)
        if existing is not None:
            return existing, False
        new_id = uuid4()
        self.ids_by_key[job.dedupe_key] = new_id
        return new_id, True

    async def claim(self) -> ClaimedJob | None:
        raise AssertionError("not exercised")

    async def ack(self, job_id: UUID) -> None:
        raise AssertionError("not exercised")

    async def fail(self, job_id: UUID, error: str) -> None:
        raise AssertionError("not exercised")


@dataclass
class SpyOpenNow:
    calls: list[tuple[UUID, int]] = field(default_factory=list)

    async def __call__(self, signal_id: UUID, poll: int) -> None:
        self.calls.append((signal_id, poll))


@dataclass
class FakeGuardedOpenNow:
    """Simulates ``ProcessSignalHandler.open_now`` re-deferring: while
    ``still_in_flight_until_poll`` has not been reached yet, it calls BACK
    into the SAME continuation's own ``seed()`` (exactly like a guard that
    is still in flight would), threading ``poll + 1`` forward itself --
    the real bug this simulates is a caller that seeded poll 0 again
    instead. Once the poll count catches up, it records the open and stops
    re-deferring.

    ``continuation`` is set AFTER construction (the same closure-style
    two-way wiring ``main.py`` uses for the real classes) since this fake
    needs to call back into the very ``OpenAfterClose`` instance it is
    injected into."""

    still_in_flight_until_poll: int
    continuation: OpenAfterClose | None = None
    opened_calls: list[UUID] = field(default_factory=list)

    async def __call__(self, signal_id: UUID, poll: int) -> None:
        assert self.continuation is not None
        if poll < self.still_in_flight_until_poll:
            await self.continuation.seed(signal_id, [], poll=poll + 1)
            return
        self.opened_calls.append(signal_id)


def _claimed_from(job: Job) -> ClaimedJob:
    """Converts an enqueued ``Job`` into the ``ClaimedJob`` a worker's next
    ``run_once`` would hand the handler -- lets a unit test drive several
    chained ``poll()`` calls without a real queue or worker loop."""
    return ClaimedJob(
        id=uuid4(), kind=job.kind, payload=job.payload, attempts=1, max_attempts=5
    )


def _signal(
    *,
    strategy_id: UUID | None = None,
    symbol: str = "STXUSDT",
    received_at: datetime = NOW,
) -> WebhookSignal:
    return WebhookSignal(
        strategy_id=strategy_id or uuid4(),
        idempotency_key=IdempotencyKey("k-1"),
        action="buy",
        contracts=Decimal("1"),
        position_size=Decimal("1"),
        price=Decimal("2"),
        symbol=symbol,
        signal_type="t",
        raw_payload={},
        id=uuid4(),
        received_at=received_at,
        status=SignalStatus.PROCESSING,
    )


def _attempt(
    *, allocation_id: UUID, status: ExecutionStatus, created_at: datetime
) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="STXUSDT.P",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=status,
        client_order_id=f"client-{allocation_id}",
        created_at=created_at,
    )


def _continuation(
    *,
    signals: FakeSignalLookupPort,
    attempts: FakeClosingAttemptsPort | None = None,
    queue: SpyJobQueue | None = None,
    open_now: SpyOpenNow | FakeGuardedOpenNow | None = None,
    clock: FrozenClock | None = None,
) -> tuple[OpenAfterClose, FakeClosingAttemptsPort, SpyJobQueue, SpyOpenNow | FakeGuardedOpenNow]:
    attempts_port = attempts or FakeClosingAttemptsPort()
    queue_port = queue or SpyJobQueue()
    open_now_port = open_now or SpyOpenNow()
    continuation = OpenAfterClose(
        signals=signals,
        attempts=attempts_port,
        queue=queue_port,
        clock=clock or FrozenClock(NOW),
        open_now=open_now_port,
        settle_timeout_seconds=SETTLE_TIMEOUT_SECONDS,
        poll_interval_seconds=POLL_INTERVAL_SECONDS,
        max_signal_age_seconds=MAX_SIGNAL_AGE_SECONDS,
    )
    return continuation, attempts_port, queue_port, open_now_port


def _job(signal_id: UUID, awaited_allocation_ids: list[UUID], poll: int = 0) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
        payload={
            "signal_id": str(signal_id),
            "awaited_allocation_ids": [str(a) for a in awaited_allocation_ids],
            "poll": poll,
        },
        attempts=1,
        max_attempts=5,
    )


async def test_seed_enqueues_the_expected_payload_and_dedupe_key() -> None:
    continuation, _, queue, _ = _continuation(signals=FakeSignalLookupPort(signal=None))
    signal_id = uuid4()
    allocation_id = uuid4()

    await continuation.seed(signal_id, [allocation_id], poll=2)

    assert len(queue.enqueued) == 1
    job = queue.enqueued[0]
    assert job.kind is JobKind.SIGNAL_OPEN_AFTER_CLOSE
    assert job.payload == {
        "signal_id": str(signal_id),
        "awaited_allocation_ids": [str(allocation_id)],
        "poll": 2,
    }
    assert job.dedupe_key == f"signal.open_after_close:{signal_id}:2"
    assert job.run_after == NOW + timedelta(seconds=POLL_INTERVAL_SECONDS)


async def test_signal_no_longer_existing_abandons_without_raising() -> None:
    continuation, _, queue, open_now = _continuation(signals=FakeSignalLookupPort(signal=None))

    await continuation.poll(_job(uuid4(), [uuid4()]))

    assert queue.enqueued == []
    assert open_now.calls == []


async def test_a_newer_signal_abandons_the_continuation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal = _signal()
    signals = FakeSignalLookupPort(signal=signal, newer=True)
    continuation, attempts, queue, open_now = _continuation(signals=signals)
    allocation_id = uuid4()

    with caplog.at_level("WARNING"):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert queue.enqueued == []
    assert open_now.calls == []
    # Superseded before it ever reads the closing attempt at all.
    assert attempts.calls == []
    assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_an_awaited_close_that_failed_abandons_with_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal = _signal()
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FAILED, created_at=NOW
            )
        }
    )
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    with caplog.at_level("ERROR"):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert queue.enqueued == []
    assert open_now.calls == []
    assert any(record.levelname == "ERROR" for record in caplog.records)


async def test_all_filled_within_the_age_bound_calls_open_now() -> None:
    signal = _signal(received_at=NOW - timedelta(seconds=10))
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FILLED, created_at=NOW
            )
        }
    )
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    await continuation.poll(_job(signal.id, [allocation_id], poll=2))

    # ``open_now`` is handed the CURRENT poll (2), not a bare "it's ready"
    # signal -- it needs this to thread ``poll + 1`` forward if it has to
    # defer again (design.md § S5, the poll-threading fix).
    assert open_now.calls == [(signal.id, 2)]
    assert queue.enqueued == []


async def test_all_filled_but_past_the_age_bound_abandons_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal = _signal(received_at=NOW - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS + 1))
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FILLED, created_at=NOW
            )
        }
    )
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    with caplog.at_level("WARNING"):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert open_now.calls == []
    assert queue.enqueued == []
    assert any(record.levelname == "WARNING" for record in caplog.records)


async def test_empty_awaited_allocations_is_vacuously_filled_and_calls_open_now() -> None:
    """The in-flight branch's own defer case (design.md § S5, amending S2):
    nothing specific to await, so the vacuous ``all()`` re-checks the whole
    guard immediately via ``open_now``."""
    signal = _signal()
    continuation, attempts, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal)
    )

    await continuation.poll(_job(signal.id, []))

    assert open_now.calls == [(signal.id, 0)]
    assert attempts.calls == []
    assert queue.enqueued == []


async def test_not_yet_filled_and_not_timed_out_reschedules_the_next_poll() -> None:
    signal = _signal()
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.SUBMITTED, created_at=NOW
            )
        }
    )
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    await continuation.poll(_job(signal.id, [allocation_id], poll=3))

    assert open_now.calls == []
    assert len(queue.enqueued) == 1
    job = queue.enqueued[0]
    assert job.payload["poll"] == 4
    assert job.dedupe_key == f"signal.open_after_close:{signal.id}:4"
    assert job.run_after == NOW + timedelta(seconds=POLL_INTERVAL_SECONDS)


async def test_not_yet_filled_past_the_settle_timeout_abandons_with_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal = _signal()
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id,
                status=ExecutionStatus.SUBMITTED,
                created_at=NOW - timedelta(seconds=SETTLE_TIMEOUT_SECONDS + 1),
            )
        }
    )
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    with caplog.at_level("ERROR"):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert open_now.calls == []
    assert queue.enqueued == []
    assert any(record.levelname == "ERROR" for record in caplog.records)


async def test_not_yet_filled_past_the_signal_age_bound_abandons_with_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even a close that is well within ITS OWN settle timeout must still
    abandon once the originating signal itself is past the 600s bound."""
    signal = _signal(received_at=NOW - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS + 1))
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.SUBMITTED, created_at=NOW
            )
        }
    )
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    with caplog.at_level("ERROR"):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert open_now.calls == []
    assert queue.enqueued == []
    assert any(record.levelname == "ERROR" for record in caplog.records)


async def test_no_closing_attempt_yet_never_times_out_on_the_settle_bound_alone() -> None:
    """``latest_close_for`` returning ``None`` (no closing attempt exists)
    must not be mistaken for an overdue one -- only the signal's own age
    bound governs until a real close attempt exists to time out on."""
    signal = _signal()
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(closes={allocation_id: None})
    continuation, _, queue, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts
    )

    await continuation.poll(_job(signal.id, [allocation_id], poll=0))

    assert open_now.calls == []
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].payload["poll"] == 1


# ---- The poll-threading fix (orchestrator-found defect) --------------------
#
# A re-defer from INSIDE ``open_now`` must seed the NEXT poll, never poll 0
# again -- seeding 0 twice collides with the already-DONE first row and
# silently drops the continuation with nothing scheduled and nothing
# logged. These prove the chain survives the guard deferring more than
# once, in every shape that can produce it.


async def test_seed_conflict_on_an_already_seeded_poll_logs_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Defensive visibility: if ``seed()`` is ever asked to re-seed a poll
    that was already seeded (the exact shape of the bug this fix removes),
    the conflict must be loud, never a silent no-op."""
    continuation, _, queue, _ = _continuation(signals=FakeSignalLookupPort(signal=None))
    signal_id = uuid4()

    await continuation.seed(signal_id, [], poll=0)
    with caplog.at_level("ERROR"):
        await continuation.seed(signal_id, [], poll=0)

    assert len(queue.enqueued) == 2
    assert any(
        record.levelname == "ERROR" and str(signal_id) in record.message
        for record in caplog.records
    )


async def test_in_flight_persisting_across_several_polls_still_opens_exactly_once() -> None:
    """(a) The guard keeps deferring (vacuous empty-awaited-ids case) for
    three polls straight, then clears -- the open must still happen, and
    exactly once, with no dedupe collision along the way."""
    signal = _signal()
    open_now = FakeGuardedOpenNow(still_in_flight_until_poll=2)
    continuation, _, queue, _ = _continuation(
        signals=FakeSignalLookupPort(signal=signal), open_now=open_now
    )
    open_now.continuation = continuation

    job = _job(signal.id, [], poll=0)
    for _ in range(5):
        await continuation.poll(job)
        if open_now.opened_calls:
            break
        assert queue.enqueued, "the chain must reschedule, never die silently"
        job = _claimed_from(queue.enqueued[-1])

    assert open_now.opened_calls == [signal.id]
    # Polls 1 and 2 were seeded (poll 0 was the job handed in, never seeded
    # by this test) -- every dedupe_key distinct, nothing reused.
    seeded_polls = [enqueued.payload["poll"] for enqueued in queue.enqueued]
    assert seeded_polls == [1, 2]
    assert len({enqueued.dedupe_key for enqueued in queue.enqueued}) == 2


async def test_in_flight_that_never_clears_keeps_rescheduling_until_the_age_bound(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(b) The guard defers on EVERY poll, forever -- the chain must keep
    rescheduling as the clock genuinely advances, and end with the
    age-bound WARNING once the signal is too old, never dying silently
    before that and never looping forever past it."""
    clock = FrozenClock(NOW)
    signal = _signal(received_at=NOW)
    queue = SpyJobQueue()
    open_now = FakeGuardedOpenNow(still_in_flight_until_poll=10_000)  # never clears
    continuation = OpenAfterClose(
        signals=FakeSignalLookupPort(signal=signal),
        attempts=FakeClosingAttemptsPort(),
        queue=queue,
        clock=clock,
        open_now=open_now,
        settle_timeout_seconds=SETTLE_TIMEOUT_SECONDS,
        poll_interval_seconds=1.0,
        max_signal_age_seconds=3.0,
    )
    open_now.continuation = continuation

    job = _job(signal.id, [], poll=0)
    previous_count = 0
    for _ in range(10):
        with caplog.at_level("WARNING"):
            await continuation.poll(job)
        if len(queue.enqueued) == previous_count:
            break
        previous_count = len(queue.enqueued)
        job = _claimed_from(queue.enqueued[-1])
        clock.advance(1.0)

    assert open_now.opened_calls == []
    assert any(record.levelname == "WARNING" for record in caplog.records)
    # The chain must have advanced through more than one poll before the
    # bound was hit -- proving it kept rescheduling rather than dying on
    # the very first re-defer (the original defect).
    assert previous_count >= 2


async def test_awaited_closes_filled_but_other_work_in_flight_continues_rather_than_dying() -> (
    None
):
    """(c) The specifically awaited close(s) are genuinely FILLED -- but
    ``open_now`` discovers some OTHER work still in flight and defers
    again. The chain must continue (seeding the next poll), not die."""
    signal = _signal()
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FILLED, created_at=NOW
            )
        }
    )
    open_now = FakeGuardedOpenNow(still_in_flight_until_poll=1)
    continuation, _, queue, _ = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts, open_now=open_now
    )
    open_now.continuation = continuation

    job = _job(signal.id, [allocation_id], poll=0)
    for _ in range(5):
        await continuation.poll(job)
        if open_now.opened_calls:
            break
        assert queue.enqueued, "the chain must reschedule, never die silently"
        job = _claimed_from(queue.enqueued[-1])

    assert open_now.opened_calls == [signal.id]
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0].payload["poll"] == 1

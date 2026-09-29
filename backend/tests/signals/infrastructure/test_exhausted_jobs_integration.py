"""Decision 25, task 5c.6 on real PostgreSQL: a signal whose job ends ``FAILED``
becomes ``REJECTED`` ``JOB_FAILED``, exactly once, in the SAME transaction as the
``FAILED`` status.

The production pieces run together: ``WorkerRunner`` claims and fails the job
through ``ExhaustionObservingJobQueue`` wired exactly as ``main.py`` wires it
(the recorder and the reader on the queue's own session). Each claim below uses
``max_attempts=1``, so the handler's one exception is the last attempt.

"Exactly once" is asserted three ways, none of which is a ``sleep(0)`` barrier:
a job reaches ``FAILED`` once (the claim lock), two exhausted jobs of ONE signal
write once (the terminal guard, silent), and a writer racing a held signal-row
lock genuinely waits (``not task.done()``) before resolving.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.shared.infrastructure.observed_job_queue import (
    ExhaustionObservingJobQueue,
)
from strategy_manager.shared.infrastructure.worker_runner import JobHandler, WorkerRunner
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.exhausted_job_recorder import (
    MAX_DETAIL_CHARS,
    ExhaustedJobSignalRecorder,
)
from strategy_manager.signals.infrastructure.failed_job_signal_reader import (
    SqlAlchemyFailedJobSignalReader,
)
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_GUARD_LOGGER = "strategy_manager.signals.infrastructure.outcome_repository"


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _observing_queue(session: AsyncSession) -> ExhaustionObservingJobQueue:
    """Built the way ``main.build_worker_runner``'s ``queue_factory`` builds it."""
    return ExhaustionObservingJobQueue(
        session,
        observer=ExhaustedJobSignalRecorder(
            SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),
            SqlAlchemyFailedJobSignalReader(session),
        ),
        backoff_base_seconds=30.0,
        backoff_max_seconds=600.0,
    )


def _runner(
    factory: async_sessionmaker[AsyncSession], kinds: list[JobKind], message: str
) -> WorkerRunner:
    @asynccontextmanager
    async def _queue_factory():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield _observing_queue(session)

    async def _boom(job: ClaimedJob) -> None:
        raise RuntimeError(message)

    handlers: dict[JobKind, JobHandler] = {kind: _boom for kind in kinds}
    return WorkerRunner(
        queue_factory=_queue_factory, handlers=handlers, poll_interval_seconds=0.01
    )


async def _enqueue(
    factory: async_sessionmaker[AsyncSession], kind: JobKind, payload: dict[str, object]
) -> UUID:
    async with factory() as session:
        job_id = await PostgresJobQueue(session).enqueue(
            Job(kind=kind, payload=payload, max_attempts=1)
        )
        await session.commit()
    return job_id


async def _claimed(
    factory: async_sessionmaker[AsyncSession], kind: JobKind, payload: dict[str, object]
) -> UUID:
    """A job already claimed once, ready for ``fail()`` to spend its last attempt."""
    job_id = await _enqueue(factory, kind, payload)
    async with factory() as session:
        claimed = await PostgresJobQueue(session).claim()
        assert claimed is not None and claimed.id == job_id
        await session.commit()
    return job_id


async def _job(factory: async_sessionmaker[AsyncSession], job_id: UUID) -> JobRow:
    async with factory() as session:
        return (await session.execute(select(JobRow).where(JobRow.id == job_id))).scalar_one()


async def _signal(factory: async_sessionmaker[AsyncSession], signal_id: UUID) -> SignalRow:
    async with factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def _decide(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID, outcome: SignalOutcome
) -> None:
    async with factory() as session:
        await SqlAlchemySignalOutcomeAdapter(session, _FixedClock()).record(signal_id, outcome)
        await session.commit()


def _guard_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == _GUARD_LOGGER]


class _Seed:
    def __init__(
        self,
        opening_signal: UUID,
        closing_signal: UUID,
        open_attempt: UUID,
        close_attempt: UUID,
    ) -> None:
        self.opening_signal = opening_signal
        self.closing_signal = closing_signal
        self.open_attempt = open_attempt
        self.close_attempt = close_attempt


async def _seed(factory: async_sessionmaker[AsyncSession]) -> _Seed:
    """An opening signal with its reservation and OPEN attempt (no link, like a
    pre-5c attempt), and a closing signal with its linked CLOSE attempt."""
    strategy_id, opening_signal, closing_signal = uuid4(), uuid4(), uuid4()
    reservation_id, open_attempt, close_attempt = uuid4(), uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    for signal_id, key, size in (
        (opening_signal, "opening", Decimal("1")),
        (closing_signal, "closing", Decimal("0")),
    ):
        await seed_signal_row(
            factory,
            signal_id=signal_id,
            strategy_id=strategy_id,
            idempotency_key=f"{key}-{signal_id}",
            symbol="STXUSDT_PERP",
            position_size=size,
            received_at=_NOW - timedelta(hours=1 if key == "opening" else 0),
        )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=opening_signal,
        status="SUBMITTED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=open_attempt,
        reservation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )
    await seed_execution_attempt(
        factory,
        attempt_id=close_attempt,
        closes_allocation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
        signal_id=closing_signal,
    )
    return _Seed(opening_signal, closing_signal, open_attempt, close_attempt)


# ---- every kind, through the real runner ------------------------------------


@pytest.mark.parametrize(
    ("kind", "payload_for", "signal_of"),
    [
        (
            JobKind.SIGNAL_PROCESS,
            lambda s: {"signal_id": str(s.opening_signal)},
            lambda s: s.opening_signal,
        ),
        (
            JobKind.SIGNAL_OPEN_AFTER_CLOSE,
            lambda s: {
                "signal_id": str(s.closing_signal),
                "awaited_allocation_ids": [],
                "poll": 2,
            },
            lambda s: s.closing_signal,
        ),
        (
            JobKind.EXECUTION_SETTLE,
            lambda s: {"execution_attempt_id": str(s.open_attempt)},
            lambda s: s.opening_signal,
        ),
        (
            JobKind.EXECUTION_SETTLE,
            lambda s: {"execution_attempt_id": str(s.close_attempt)},
            lambda s: s.closing_signal,
        ),
    ],
    ids=["signal.process", "signal.open_after_close", "settle-open", "settle-close"],
)
async def test_a_job_that_exhausts_its_retries_rejects_its_signal(
    pg_session_factory: async_sessionmaker[AsyncSession], kind, payload_for, signal_of  # type: ignore[no-untyped-def]
) -> None:
    seed = await _seed(pg_session_factory)
    job_id = await _enqueue(pg_session_factory, kind, payload_for(seed))

    ran = await _runner(pg_session_factory, [kind], "the venue is down").run_once()

    assert ran is True
    job = await _job(pg_session_factory, job_id)
    assert (job.status, job.last_error) == ("FAILED", "the venue is down")
    signal = await _signal(pg_session_factory, signal_of(seed))
    assert (signal.status, signal.outcome_reason, signal.outcome_detail) == (
        "REJECTED",
        "JOB_FAILED",
        "the venue is down",
    )
    assert signal.decided_at == _NOW


async def test_a_settle_job_for_a_close_does_not_reject_the_opening_signal(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await _seed(pg_session_factory)
    await _enqueue(
        pg_session_factory,
        JobKind.EXECUTION_SETTLE,
        {"execution_attempt_id": str(seed.close_attempt)},
    )

    await _runner(pg_session_factory, [JobKind.EXECUTION_SETTLE], "boom").run_once()

    assert (await _signal(pg_session_factory, seed.opening_signal)).status == "ACCEPTED"


async def test_a_job_that_will_be_retried_leaves_its_signal_alone(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await _seed(pg_session_factory)
    async with pg_session_factory() as session:
        await PostgresJobQueue(session).enqueue(
            Job(
                kind=JobKind.SIGNAL_PROCESS,
                payload={"signal_id": str(seed.opening_signal)},
                max_attempts=3,
            )
        )
        await session.commit()

    await _runner(pg_session_factory, [JobKind.SIGNAL_PROCESS], "transient").run_once()

    assert (await _signal(pg_session_factory, seed.opening_signal)).status == "ACCEPTED"


async def test_the_detail_is_the_error_bounded_and_redacted_in_the_row(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await _seed(pg_session_factory)
    await _enqueue(
        pg_session_factory, JobKind.SIGNAL_PROCESS, {"signal_id": str(seed.opening_signal)}
    )
    message = "connect failed for postgresql://app:hunter2@db/app " + "z" * 5000

    await _runner(pg_session_factory, [JobKind.SIGNAL_PROCESS], message).run_once()

    signal = await _signal(pg_session_factory, seed.opening_signal)
    assert signal.outcome_detail is not None
    assert len(signal.outcome_detail) == MAX_DETAIL_CHARS
    assert "hunter2" not in signal.outcome_detail


# ---- never over a terminal signal, exactly once ------------------------------


@pytest.mark.parametrize(
    "held",
    [
        SignalOutcome.processed(),
        SignalOutcome.rejected("CLOSE_REJECTED_BY_VENUE", "refused earlier"),
    ],
    ids=["processed", "rejected"],
)
async def test_an_exhausted_job_never_overwrites_a_terminal_signal_and_does_not_warn(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
    held: SignalOutcome,
) -> None:
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    seed = await _seed(pg_session_factory)
    await _decide(pg_session_factory, seed.opening_signal, held)
    before = await _signal(pg_session_factory, seed.opening_signal)
    job_id = await _enqueue(
        pg_session_factory, JobKind.SIGNAL_PROCESS, {"signal_id": str(seed.opening_signal)}
    )

    await _runner(pg_session_factory, [JobKind.SIGNAL_PROCESS], "late failure").run_once()

    assert (await _job(pg_session_factory, job_id)).status == "FAILED"
    after = await _signal(pg_session_factory, seed.opening_signal)
    assert (after.status, after.outcome_reason, after.outcome_detail, after.decided_at) == (
        before.status,
        before.outcome_reason,
        before.outcome_detail,
        before.decided_at,
    )
    assert _guard_records(caplog) == []


async def test_two_exhausted_jobs_of_one_signal_write_exactly_once(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """``signal.process`` and the ``execution.settle`` of its open both die: the
    signal ends ``JOB_FAILED`` once, with the FIRST error, and the second job is
    a silent no-op (not a second write, not a WARNING)."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    seed = await _seed(pg_session_factory)
    first = await _claimed(
        pg_session_factory, JobKind.SIGNAL_PROCESS, {"signal_id": str(seed.opening_signal)}
    )
    second = await _claimed(
        pg_session_factory,
        JobKind.EXECUTION_SETTLE,
        {"execution_attempt_id": str(seed.open_attempt)},
    )

    async with pg_session_factory() as session:
        await _observing_queue(session).fail(first, "first error")
    decided = await _signal(pg_session_factory, seed.opening_signal)
    async with pg_session_factory() as session:
        await _observing_queue(session).fail(second, "second error")

    signal = await _signal(pg_session_factory, seed.opening_signal)
    assert (signal.status, signal.outcome_reason, signal.outcome_detail) == (
        "REJECTED",
        "JOB_FAILED",
        "first error",
    )
    assert signal.decided_at == decided.decided_at
    assert (await _job(pg_session_factory, second)).status == "FAILED"  # still marked FAILED
    assert _guard_records(caplog) == []


async def test_a_failed_commit_loses_the_failed_status_and_the_rejection_together(
    pg_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A redelivery after that failed commit still records exactly once."""
    seed = await _seed(pg_session_factory)
    job_id = await _claimed(
        pg_session_factory, JobKind.SIGNAL_PROCESS, {"signal_id": str(seed.opening_signal)}
    )

    async with pg_session_factory() as session:

        async def _failing_commit() -> None:
            await session.rollback()
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(session, "commit", _failing_commit)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _observing_queue(session).fail(job_id, "boom")

    assert (await _job(pg_session_factory, job_id)).status == "CLAIMED"
    assert (await _signal(pg_session_factory, seed.opening_signal)).status == "ACCEPTED"

    async with pg_session_factory() as session:  # the redelivered failure
        await _observing_queue(session).fail(job_id, "boom")

    signal = await _signal(pg_session_factory, seed.opening_signal)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "JOB_FAILED")
    assert (await _job(pg_session_factory, job_id)).status == "FAILED"


async def test_the_exhaustion_write_waits_for_a_concurrent_writer_holding_the_signal_row(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """Lock-hold harness. Session B decided the signal and keeps its
    transaction open (row locked); the exhaustion of a job of that signal must
    WAIT (``not task.done()`` after a real delay). Once B commits it finds the
    signal terminal and stays silent, and the job is still ``FAILED``."""
    caplog.set_level(logging.WARNING, logger=_GUARD_LOGGER)
    seed = await _seed(pg_session_factory)
    job_id = await _claimed(
        pg_session_factory, JobKind.SIGNAL_PROCESS, {"signal_id": str(seed.opening_signal)}
    )

    async with pg_session_factory() as session_b, pg_session_factory() as session_a:
        await SqlAlchemySignalOutcomeAdapter(session_b, _FixedClock()).record(
            seed.opening_signal, SignalOutcome.rejected("PAIR_NOT_ALLOWED", "b holds the lock")
        )

        async def _a_fails() -> None:
            await _observing_queue(session_a).fail(job_id, "a waited")

        task = asyncio.create_task(_a_fails())
        await asyncio.sleep(0.5)
        assert not task.done(), "the exhaustion write must block on the row B holds locked"

        await session_b.commit()
        await asyncio.wait_for(task, timeout=10)

    signal = await _signal(pg_session_factory, seed.opening_signal)
    assert (signal.status, signal.outcome_reason) == ("REJECTED", "PAIR_NOT_ALLOWED")
    assert (await _job(pg_session_factory, job_id)).status == "FAILED"
    assert _guard_records(caplog) == []

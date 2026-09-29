"""``ExhaustionObservingJobQueue`` against a real PostgreSQL queue (decision 25,
task 5c.6): the observer is told about a job the moment it spends its last
attempt, in the SAME transaction as the ``FAILED`` status, and its own failure
never costs the job that status.

What a real database proves that a fake cannot: that the observer's writes and
the status land together or not at all (a fault on the one commit loses both),
and that a SAVEPOINT really contains an observer whose statement aborted the
transaction.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.shared.infrastructure.observed_job_queue import (
    ExhaustionObservingJobQueue,
)
from strategy_manager.shared.infrastructure.worker_runner import WorkerRunner

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_LOGGER = "strategy_manager.shared.infrastructure.observed_job_queue"


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


class _Observer:
    """Records every call, and stages one marker job on the queue's own
    session so a test can see whether the observer's write committed."""

    def __init__(self, session: AsyncSession, *, raises: Exception | None = None) -> None:
        self._session = session
        self._raises = raises
        self.calls: list[tuple[ClaimedJob, str]] = []

    async def on_exhausted(self, job: ClaimedJob, last_error: str) -> None:
        self.calls.append((job, last_error))
        await PostgresJobQueue(self._session, clock=_FixedClock()).enqueue(
            Job(kind=JobKind.JOBS_PURGE, payload={"marker": str(job.id)})
        )
        if self._raises is not None:
            raise self._raises


class _AbortingObserver:
    """Aborts the surrounding transaction with a statement Postgres rejects."""

    async def on_exhausted(self, job: ClaimedJob, last_error: str) -> None:
        self.session: AsyncSession
        await self.session.execute(text("SELECT * FROM a_table_that_does_not_exist"))


def _queue(session: AsyncSession, observer: object) -> ExhaustionObservingJobQueue:
    return ExhaustionObservingJobQueue(
        session,
        observer=observer,  # type: ignore[arg-type]
        clock=_FixedClock(),
        backoff_base_seconds=30.0,
        backoff_max_seconds=600.0,
    )


async def _claimed(
    factory: async_sessionmaker[AsyncSession],
    *,
    max_attempts: int,
    kind: JobKind = JobKind.SIGNAL_PROCESS,
) -> UUID:
    """A job that a queue has claimed once (attempts=1)."""
    async with factory() as session:
        queue = PostgresJobQueue(session, clock=_FixedClock())
        job_id = await queue.enqueue(
            Job(kind=kind, payload={"signal_id": str(uuid4())}, max_attempts=max_attempts)
        )
        await session.commit()
    async with factory() as session:
        claimed = await PostgresJobQueue(session, clock=_FixedClock()).claim()
        assert claimed is not None and claimed.id == job_id
        await session.commit()
    return job_id


async def _job(factory: async_sessionmaker[AsyncSession], job_id: UUID) -> JobRow:
    async with factory() as session:
        return (await session.execute(select(JobRow).where(JobRow.id == job_id))).scalar_one()


async def _markers(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        rows = (
            await session.execute(select(JobRow).where(JobRow.kind == JobKind.JOBS_PURGE.value))
        ).scalars()
        return len(list(rows))


async def test_a_failure_that_will_be_retried_is_not_reported(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _claimed(pg_session_factory, max_attempts=3)

    async with pg_session_factory() as session:
        observer = _Observer(session)
        await _queue(session, observer).fail(job_id, "transient")

    assert observer.calls == []
    assert (await _job(pg_session_factory, job_id)).status == "PENDING"
    assert await _markers(pg_session_factory) == 0


async def test_the_failure_that_spends_the_last_attempt_is_reported_once_with_the_job(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _claimed(pg_session_factory, max_attempts=1)

    async with pg_session_factory() as session:
        observer = _Observer(session)
        await _queue(session, observer).fail(job_id, "the venue refused it")

    assert len(observer.calls) == 1
    [(job, error)] = observer.calls
    assert error == "the venue refused it"
    assert (job.id, job.kind, job.attempts, job.max_attempts) == (
        job_id,
        JobKind.SIGNAL_PROCESS,
        1,
        1,
    )
    assert set(job.payload) == {"signal_id"}
    row = await _job(pg_session_factory, job_id)
    assert (row.status, row.last_error) == ("FAILED", "the venue refused it")
    assert await _markers(pg_session_factory) == 1


async def test_the_observers_write_and_the_failed_status_commit_together_or_not_at_all(
    pg_session_factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction: with the commit failing, neither the ``FAILED`` status
    nor the observer's marker survives; without a fault both do, on exactly one
    commit (a marker on a commit of its own would pass the fault half of this
    test on a vacuous rollback, and fail the commit count)."""
    faulty_id = await _claimed(pg_session_factory, max_attempts=1)
    async with pg_session_factory() as session:
        real_commit = session.commit

        async def _failing_commit() -> None:
            await session.rollback()
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(session, "commit", _failing_commit)
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await _queue(session, _Observer(session)).fail(faulty_id, "boom")
        monkeypatch.setattr(session, "commit", real_commit)

    assert (await _job(pg_session_factory, faulty_id)).status == "CLAIMED"
    assert await _markers(pg_session_factory) == 0

    clean_id = await _claimed(pg_session_factory, max_attempts=1)
    async with pg_session_factory() as session:
        commits: list[int] = []
        original_commit = session.commit

        async def _counting_commit() -> None:
            commits.append(1)
            await original_commit()

        monkeypatch.setattr(session, "commit", _counting_commit)
        await _queue(session, _Observer(session)).fail(clean_id, "boom")

    assert len(commits) == 1
    assert (await _job(pg_session_factory, clean_id)).status == "FAILED"
    assert await _markers(pg_session_factory) == 1


async def test_an_observer_that_raises_costs_the_job_neither_its_status_nor_the_loop(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    """The failure is logged (ERROR, redacted), what the observer had staged is
    rolled back with its savepoint, and the job is still ``FAILED``."""
    job_id = await _claimed(pg_session_factory, max_attempts=1)

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        async with pg_session_factory() as session:
            observer = _Observer(
                session, raises=RuntimeError("write failed for postgresql://u:hunter2@db/app")
            )
            await _queue(session, observer).fail(job_id, "boom")

    assert (await _job(pg_session_factory, job_id)).status == "FAILED"
    assert await _markers(pg_session_factory) == 0  # rolled back with the savepoint
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert str(job_id) in errors[0]
    assert "hunter2" not in errors[0]


async def test_an_observer_whose_statement_aborts_the_transaction_is_contained(
    pg_session_factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    job_id = await _claimed(pg_session_factory, max_attempts=1)

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        async with pg_session_factory() as session:
            observer = _AbortingObserver()
            observer.session = session
            await _queue(session, observer).fail(job_id, "boom")

    assert (await _job(pg_session_factory, job_id)).status == "FAILED"
    assert len([r for r in caplog.records if r.levelno == logging.ERROR]) == 1


async def test_the_worker_runner_reports_an_exhausted_job_and_survives_a_failing_observer(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    job_id = await _claimed(pg_session_factory, max_attempts=1)
    # ``run_once`` claims a PENDING job, so put it back as the claim would find it.
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE jobs SET status = 'PENDING', attempts = 0 WHERE id = :id"),
            {"id": job_id},
        )
        await session.commit()

    seen: list[str] = []

    class _Failing:
        async def on_exhausted(self, job: ClaimedJob, last_error: str) -> None:
            seen.append(last_error)
            raise RuntimeError("observer down")

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _factory():  # type: ignore[no-untyped-def]
        async with pg_session_factory() as session:
            yield _queue(session, _Failing())

    async def _handler(job: ClaimedJob) -> None:
        raise ValueError("handler blew up")

    runner = WorkerRunner(
        queue_factory=_factory,
        handlers={JobKind.SIGNAL_PROCESS: _handler},
        poll_interval_seconds=0.01,
    )

    assert await runner.run_once() is True  # did not raise out of the loop
    assert seen == ["handler blew up"]
    row = await _job(pg_session_factory, job_id)
    assert (row.status, row.last_error) == ("FAILED", "handler blew up")

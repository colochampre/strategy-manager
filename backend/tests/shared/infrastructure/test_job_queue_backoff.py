"""Retry backoff — integration against a real PostgreSQL queue.

A failed job used to come back PENDING with ``run_after`` untouched, so the
worker reclaimed it on the very next poll. On 2026-09-18 that burned five
attempts in 27 seconds and killed the ``balance.sync`` chain outright, from a
clock excursion the venue had already corrected by the time anyone looked.

The delay is what turns a transient fault into a wait rather than a death
sentence, so these tests assert the ``run_after`` actually written against a
clock the test controls — not that some internal helper was called.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow

pytestmark = pytest.mark.integration

START = datetime(2026, 9, 18, 10, 15, 0, tzinfo=UTC)


class SteppableClock:
    """A clock the test moves by hand, so a retry scheduled minutes out can be
    observed without the test waiting for it."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)


async def _retry_state(session: AsyncSession, job_id: UUID) -> tuple[str, datetime]:
    result = await session.execute(
        select(JobRow.status, JobRow.run_after).where(JobRow.id == job_id)
    )
    row = result.one()
    return row.status, row.run_after


async def test_the_first_failure_schedules_the_retry_one_base_delay_out(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = SteppableClock(START)

    async with pg_session_factory() as session:
        queue = PostgresJobQueue(
            session, clock=clock, backoff_base_seconds=30.0, backoff_max_seconds=600.0
        )
        job_id = await queue.enqueue(Job(kind=JobKind.BALANCE_SYNC))
        await session.commit()

        claimed = await queue.claim()
        assert claimed is not None
        # ``attempts`` is incremented at claim time, so the first failure is
        # attempt 1 and must wait exactly one base delay, not two.
        assert claimed.attempts == 1
        await queue.fail(claimed.id, "server_timestamp ahead of req_timestamp")

        status, run_after = await _retry_state(session, job_id)

    assert status == "PENDING"
    assert run_after == START + timedelta(seconds=30)


async def test_the_retry_delay_doubles_with_every_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = SteppableClock(START)
    delays: list[float] = []

    async with pg_session_factory() as session:
        queue = PostgresJobQueue(
            session, clock=clock, backoff_base_seconds=30.0, backoff_max_seconds=600.0
        )
        job_id = await queue.enqueue(Job(kind=JobKind.BALANCE_SYNC, max_attempts=5))
        await session.commit()

        for _ in range(4):
            claimed = await queue.claim()
            assert claimed is not None
            failed_at = clock.now()
            await queue.fail(claimed.id, "boom")

            status, run_after = await _retry_state(session, job_id)
            assert status == "PENDING"
            delay = (run_after - failed_at).total_seconds()
            delays.append(delay)
            # Move to the moment the retry is due, so the next claim can take it.
            clock.advance(delay)

    assert delays == [30.0, 60.0, 120.0, 240.0]


async def test_the_retry_delay_stops_growing_at_the_cap(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    clock = SteppableClock(START)
    delays: list[float] = []

    async with pg_session_factory() as session:
        queue = PostgresJobQueue(
            session, clock=clock, backoff_base_seconds=30.0, backoff_max_seconds=100.0
        )
        job_id = await queue.enqueue(Job(kind=JobKind.BALANCE_SYNC, max_attempts=5))
        await session.commit()

        for _ in range(4):
            claimed = await queue.claim()
            assert claimed is not None
            failed_at = clock.now()
            await queue.fail(claimed.id, "boom")

            _, run_after = await _retry_state(session, job_id)
            delay = (run_after - failed_at).total_seconds()
            delays.append(delay)
            clock.advance(delay)

    assert delays == [30.0, 60.0, 100.0, 100.0]


async def test_a_job_that_exhausted_its_attempts_is_failed_and_not_rescheduled(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Backoff buys time; it does not buy extra attempts. The last failure ends
    the job exactly as it did before, with ``run_after`` left alone."""
    clock = SteppableClock(START)

    async with pg_session_factory() as session:
        queue = PostgresJobQueue(
            session, clock=clock, backoff_base_seconds=30.0, backoff_max_seconds=600.0
        )
        job_id = await queue.enqueue(Job(kind=JobKind.BALANCE_SYNC, max_attempts=1))
        await session.commit()

        claimed = await queue.claim()
        assert claimed is not None
        assert claimed.attempts == 1
        await queue.fail(claimed.id, "boom")

        status, run_after = await _retry_state(session, job_id)

    assert status == "FAILED"
    assert run_after == START

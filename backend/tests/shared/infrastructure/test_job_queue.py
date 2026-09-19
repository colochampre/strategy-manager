"""Integration tests against a real PostgreSQL database (strategy_manager_test).

Covers spec: job-queue § SKIP LOCKED Claim, § Crash Reclaim, § Acknowledge and
Retry. Each test opens its own physical connection(s) via ``pg_session_factory``
because SKIP LOCKED visibility and crash-reclaim both depend on distinct
connections observing each other's row locks.
"""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue

pytestmark = pytest.mark.integration


async def _enqueue_committed(
    session_factory: async_sessionmaker[AsyncSession], job: Job
) -> None:
    async with session_factory() as session:
        await PostgresJobQueue(session).enqueue(job)
        await session.commit()


async def test_concurrent_workers_claim_distinct_jobs_and_neither_blocks(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _enqueue_committed(pg_session_factory, Job(kind=JobKind.SIGNAL_PROCESS, payload={"n": 1}))
    await _enqueue_committed(pg_session_factory, Job(kind=JobKind.SIGNAL_PROCESS, payload={"n": 2}))

    # Two distinct, still-open sessions/connections: closing a session would
    # roll back its uncommitted CLAIMED write and release the row lock, which
    # would defeat the exclusivity this test verifies.
    session_a = pg_session_factory()
    session_b = pg_session_factory()
    try:
        results = await asyncio.gather(
            PostgresJobQueue(session_a).claim(), PostgresJobQueue(session_b).claim()
        )
    finally:
        await session_a.close()
        await session_b.close()

    assert all(claimed is not None for claimed in results)
    claimed_ids = {claimed.id for claimed in results}  # type: ignore[union-attr]
    assert len(claimed_ids) == 2


async def test_no_available_jobs_poll_returns_none_cleanly(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        claimed = await PostgresJobQueue(session).claim()

    assert claimed is None


async def test_crash_reclaim_releases_the_job_when_the_connection_terminates_before_commit(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _enqueue_committed(
        pg_session_factory, Job(kind=JobKind.RESERVATION_SWEEP, payload={})
    )

    crashing_session = pg_session_factory()
    claimed_before_crash = await PostgresJobQueue(crashing_session).claim()
    assert claimed_before_crash is not None
    # Simulate the worker's connection terminating before it acknowledges the
    # job: close without committing. SQLAlchemy rolls back the open
    # transaction, which reverts the CLAIMED write and releases the row lock.
    await crashing_session.close()

    async with pg_session_factory() as recovering_session:
        reclaimed = await PostgresJobQueue(recovering_session).claim()

    assert reclaimed is not None
    assert reclaimed.id == claimed_before_crash.id


async def test_successful_processing_acknowledges_the_job_and_it_is_never_reclaimed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _enqueue_committed(pg_session_factory, Job(kind=JobKind.SIGNAL_PROCESS, payload={}))

    async with pg_session_factory() as session:
        queue = PostgresJobQueue(session)
        claimed = await queue.claim()
        assert claimed is not None
        await queue.ack(claimed.id)

    async with pg_session_factory() as session:
        never_reclaimed = await PostgresJobQueue(session).claim()

    assert never_reclaimed is None


async def test_failed_processing_allows_the_job_to_be_claimed_again(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Failing below ``max_attempts`` returns the job to the queue rather than
    ending it.

    The wait before it is claimable again is zeroed here on purpose: the delay
    is its own behaviour and ``test_job_queue_backoff.py`` owns it, while this
    test is about the retry existing at all.
    """
    await _enqueue_committed(pg_session_factory, Job(kind=JobKind.SIGNAL_PROCESS, payload={}))

    async with pg_session_factory() as session:
        queue = PostgresJobQueue(session, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
        claimed = await queue.claim()
        assert claimed is not None
        await queue.fail(claimed.id, "boom")

    async with pg_session_factory() as session:
        retried = await PostgresJobQueue(session).claim()

    assert retried is not None
    assert retried.id == claimed.id
    assert retried.attempts == 2

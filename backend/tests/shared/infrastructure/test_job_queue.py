"""Integration tests against a real PostgreSQL database (strategy_manager_test).

Covers spec: job-queue § SKIP LOCKED Claim, § Crash Reclaim, § Acknowledge and
Retry. Each test opens its own physical connection(s) via ``pg_session_factory``
because SKIP LOCKED visibility and crash-reclaim both depend on distinct
connections observing each other's row locks.
"""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow

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


async def test_one_job_is_never_handed_to_two_workers_at_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The structural half of continuation idempotency (spec: job-queue §
    Continuation Idempotency, § SKIP LOCKED Claim).

    ``ProcessSignalHandler.open_now`` must not submit two opens for one
    signal. One way two deliveries could exist at once is the queue handing
    the SAME ``signal.open_after_close`` row to two workers. It cannot:
    ``claim()`` selects ``FOR UPDATE SKIP LOCKED``, so the second worker
    steps over the locked row and finds nothing rather than waiting for it.

    The interesting assertion is the last one. The loser is turned away by
    the ROW LOCK, not by a status it can see: the winner has not committed,
    so a third connection still reads the job as ``PENDING``. Without
    ``SKIP LOCKED`` that same claim would block on the lock instead of
    returning, and this test would hang rather than pass.

    It is the exact counterpart of
    ``test_concurrent_workers_claim_distinct_jobs_and_neither_blocks``
    above: identical harness, two jobs there and two claims, one job here
    and one claim. Neither result is reachable by accident from the other.
    """
    await _enqueue_committed(
        pg_session_factory,
        Job(
            kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
            payload={"signal_id": "5a1d1f1e-0000-4000-8000-000000000001", "poll": 0},
            dedupe_key="signal.open_after_close:5a1d1f1e-0000-4000-8000-000000000001:0",
        ),
    )

    session_a = pg_session_factory()
    session_b = pg_session_factory()
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                PostgresJobQueue(session_a).claim(), PostgresJobQueue(session_b).claim()
            ),
            timeout=10.0,
        )

        # Read from a THIRD connection while the winner's CLAIMED write is
        # still uncommitted.
        async with pg_session_factory() as observer:
            status_during_claim = (
                await observer.execute(select(JobRow.status))
            ).scalar_one()
    finally:
        await session_a.close()
        await session_b.close()

    claimed = [result for result in results if result is not None]
    empty = [result for result in results if result is None]

    assert len(claimed) == 1
    assert len(empty) == 1
    assert claimed[0].kind is JobKind.SIGNAL_OPEN_AFTER_CLOSE
    assert status_during_claim == "PENDING"


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


async def test_enqueue_unique_first_call_inserts_and_returns_a_new_id(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        job_id, inserted = await PostgresJobQueue(session).enqueue_unique(
            Job(
                kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
                payload={"signal_id": "abc", "poll": 0},
                dedupe_key="signal.open_after_close:abc:0",
            )
        )
        await session.commit()

    assert inserted is True

    async with pg_session_factory() as session:
        claimed = await PostgresJobQueue(session).claim()

    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.kind is JobKind.SIGNAL_OPEN_AFTER_CLOSE


async def test_enqueue_unique_second_call_with_the_same_dedupe_key_returns_the_existing_id(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    dedupe_key = "signal.open_after_close:def:1"

    async with pg_session_factory() as session:
        first_id, first_inserted = await PostgresJobQueue(session).enqueue_unique(
            Job(kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE, payload={"poll": 1}, dedupe_key=dedupe_key)
        )
        await session.commit()

    assert first_inserted is True

    async with pg_session_factory() as session:
        second_id, second_inserted = await PostgresJobQueue(session).enqueue_unique(
            Job(kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE, payload={"poll": 1}, dedupe_key=dedupe_key)
        )
        await session.commit()

    assert second_id == first_id
    assert second_inserted is False

    async with pg_session_factory() as session:
        count = await session.execute(
            select(func.count())
            .select_from(JobRow)
            .where(JobRow.dedupe_key == dedupe_key)
        )
        assert count.scalar_one() == 1


async def test_enqueue_unique_does_not_commit_and_stays_inside_the_callers_transaction(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """design.md § S5: the seed must be committed atomically with the
    caller's own write (the close attempt), inside the SAME transaction --
    a caller that never commits must see nothing durable."""

    session = pg_session_factory()
    try:
        await PostgresJobQueue(session).enqueue_unique(
            Job(kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE, payload={}, dedupe_key="never-committed")
        )
        # Simulate a crash before the caller's own commit: close without
        # committing, exactly like the crash-reclaim test above.
        await session.close()
    finally:
        pass

    async with pg_session_factory() as session:
        count = await session.execute(
            select(func.count())
            .select_from(JobRow)
            .where(JobRow.dedupe_key == "never-committed")
        )
        assert count.scalar_one() == 0


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

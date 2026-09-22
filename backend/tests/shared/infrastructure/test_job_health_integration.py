"""``PostgresJobHealth`` — the watchdog's two questions, against real SQL.

Both are questions about ABSENCE, which is exactly the class of thing a fake
cannot pin: "no claimable job exists for this kind" and "nothing failed in this
window" are answers produced by the WHERE clause, so the query is the
behaviour. A fake that returned the right shape would prove nothing about
either.

The statuses are the whole subtlety. ``PENDING`` and ``CLAIMED`` are both
alive — a chain whose job is currently being worked on has not stopped — while
``DONE`` and ``FAILED`` are both finished, and a chain whose last row is DONE
has nothing scheduled at all. That is the three-day production failure
(2026-09-18 to 2026-09-21) stated as a query.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.watchdog import FailedJobs
from strategy_manager.shared.infrastructure.job_health import PostgresJobHealth

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
WINDOW_START = NOW - timedelta(seconds=300)

KINDS = (JobKind.BALANCE_SYNC, JobKind.RESERVATION_SWEEP, JobKind.JOBS_PURGE)


async def _insert(
    factory: async_sessionmaker[AsyncSession],
    kind: JobKind,
    status: str,
    updated_at: datetime = NOW,
    count: int = 1,
) -> None:
    async with factory() as session:
        for _ in range(count):
            await session.execute(
                text(
                    "INSERT INTO jobs (kind, payload, status, updated_at) "
                    "VALUES (:kind, '{}'::jsonb, :status, :updated_at)"
                ),
                {"kind": kind.value, "status": status, "updated_at": updated_at},
            )
        await session.commit()


async def _unscheduled(
    factory: async_sessionmaker[AsyncSession],
) -> list[JobKind]:
    async with factory() as session:
        return list(await PostgresJobHealth(session).kinds_without_live_job(KINDS))


async def _failures(
    factory: async_sessionmaker[AsyncSession], since: datetime = WINDOW_START
) -> list[FailedJobs]:
    async with factory() as session:
        return list(await PostgresJobHealth(session).failures_since(since))


# --- nothing scheduled ----------------------------------------------------


async def test_a_kind_with_no_rows_at_all_has_nothing_scheduled(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _unscheduled(pg_session_factory) == list(KINDS)


async def test_a_pending_job_keeps_its_chain_alive(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "PENDING")

    unscheduled = await _unscheduled(pg_session_factory)

    assert JobKind.BALANCE_SYNC not in unscheduled
    assert JobKind.RESERVATION_SWEEP in unscheduled


async def test_a_claimed_job_keeps_its_chain_alive_too(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A job being worked on right now is not a dead chain. The successor is
    enqueued by the handler before the worker acks, so a healthy chain is
    never momentarily empty — and reading CLAIMED as dead would make the
    watchdog fire on every long-running job."""
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "CLAIMED")

    assert JobKind.BALANCE_SYNC not in await _unscheduled(pg_session_factory)


async def test_a_chain_whose_last_row_is_done_has_nothing_scheduled(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The successor enqueue is what keeps these chains alive. A DONE row
    with no successor means the chain ended — quietly, which is the point."""
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "DONE", count=50)

    assert JobKind.BALANCE_SYNC in await _unscheduled(pg_session_factory)


async def test_a_chain_whose_last_row_is_failed_has_nothing_scheduled(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """This is the incident itself: ``fail()`` writes FAILED once
    ``max_attempts`` is spent, nothing raises, and nothing is scheduled."""
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "FAILED")

    assert JobKind.BALANCE_SYNC in await _unscheduled(pg_session_factory)


async def test_another_kind_s_pending_job_does_not_cover_for_this_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(pg_session_factory, JobKind.JOBS_PURGE, "PENDING")

    assert await _unscheduled(pg_session_factory) == [
        JobKind.BALANCE_SYNC,
        JobKind.RESERVATION_SWEEP,
    ]


# --- what failed since the previous run -----------------------------------


async def test_failures_are_counted_per_kind(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "FAILED", count=3)
    await _insert(pg_session_factory, JobKind.JOBS_PURGE, "FAILED", count=1)

    assert await _failures(pg_session_factory) == [
        FailedJobs(kind=JobKind.BALANCE_SYNC.value, count=3),
        FailedJobs(kind=JobKind.JOBS_PURGE.value, count=1),
    ]


async def test_a_failure_older_than_the_window_is_not_reported_again(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``jobs.purge`` never deletes a FAILED row, so every failure this
    deployment has ever had is still in the table. Without the window the
    watchdog would re-report all of them on every single run."""
    await _insert(
        pg_session_factory,
        JobKind.BALANCE_SYNC,
        "FAILED",
        updated_at=WINDOW_START - timedelta(seconds=1),
    )

    assert await _failures(pg_session_factory) == []


async def test_a_failure_exactly_at_the_window_edge_is_reported(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The bound is inclusive: the previous run's own ``checked_at`` becomes
    this one's ``since``, so an exclusive bound would drop a job that failed
    in the same instant the previous run read the table."""
    await _insert(
        pg_session_factory, JobKind.BALANCE_SYNC, "FAILED", updated_at=WINDOW_START
    )

    assert await _failures(pg_session_factory) == [
        FailedJobs(kind=JobKind.BALANCE_SYNC.value, count=1)
    ]


async def test_a_job_that_is_only_retrying_is_not_a_failure(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``fail()`` puts a retryable job back to PENDING with its error stored.
    Reporting that as a failure would alert on every transient fault the retry
    chain exists to absorb."""
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "PENDING")
    await _insert(pg_session_factory, JobKind.BALANCE_SYNC, "DONE")

    assert await _failures(pg_session_factory) == []

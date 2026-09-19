"""``PostgresJobRetention`` + ``PurgeJobs`` — against a real PostgreSQL queue.

The ``jobs`` table has no external reaper: ``ack`` marks a row DONE and nothing
ever removes it, so the table grows for as long as the worker runs. This is the
only thing that deletes from it, which makes WHAT it refuses to delete the
property worth pinning against the real SQL rather than a fake.

**FAILED is never deleted.** A job that exhausted ``max_attempts`` is the only
surviving evidence that a self-scheduling chain died silently — nothing raises
when it happens, and ``RecurringJobSeeder``'s docstring names a worker restart
as the recovery. Purging that row would erase the trace of the outage along
with it.

Deleting DONE rows is safe for the two mechanisms that might look like they
depend on them, and neither does: duplicate webhooks are blocked by
``ux_signals_idempotency`` on the ``signals`` table, and ``RecurringJobSeeder``
looks only for PENDING/CLAIMED — deliberately, so a lingering DONE row can
never block a chain from being re-seeded.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.purge_jobs import PurgeJobs, PurgeResult
from strategy_manager.shared.infrastructure.job_retention import PostgresJobRetention
from strategy_manager.shared.infrastructure.models import JobRow

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
RETENTION_DAYS = 7
OLD = NOW - timedelta(days=RETENTION_DAYS + 1)
RECENT = NOW - timedelta(days=RETENTION_DAYS - 1)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


async def _insert(
    factory: async_sessionmaker[AsyncSession],
    status: str,
    updated_at: datetime,
    count: int = 1,
) -> None:
    async with factory() as session:
        for _ in range(count):
            await session.execute(
                text(
                    "INSERT INTO jobs (kind, payload, status, updated_at) "
                    "VALUES (:kind, '{}'::jsonb, :status, :updated_at)"
                ),
                {
                    "kind": JobKind.JOBS_PURGE.value,
                    "status": status,
                    "updated_at": updated_at,
                },
            )
        await session.commit()


async def _statuses(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with factory() as session:
        result = await session.execute(select(JobRow.status).order_by(JobRow.status))
        return [str(status) for status in result.scalars().all()]


async def _count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        result = await session.execute(select(func.count()).select_from(JobRow))
        return int(result.scalar_one())


async def _purge(
    factory: async_sessionmaker[AsyncSession],
    *,
    batch_size: int = 1_000,
    max_rows_per_run: int = 100_000,
) -> PurgeResult:
    async with factory() as session:
        return await PurgeJobs(
            retention=PostgresJobRetention(session),
            clock=FrozenClock(),
            commit=session,
            retention_days=RETENTION_DAYS,
            batch_size=batch_size,
            max_rows_per_run=max_rows_per_run,
        ).purge()


async def test_a_done_row_past_the_window_is_deleted(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(pg_session_factory, "DONE", OLD)

    result = await _purge(pg_session_factory)

    assert result.deleted == 1
    assert await _count(pg_session_factory) == 0


async def test_a_done_row_inside_the_window_is_kept(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(pg_session_factory, "DONE", RECENT)

    result = await _purge(pg_session_factory)

    assert result.deleted == 0
    assert await _statuses(pg_session_factory) == ["DONE"]


async def test_a_failed_row_past_the_window_is_kept(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FAILED is evidence, not garbage: it is the only record that a chain
    exhausted its retries and stopped, and nothing else reports that."""

    await _insert(pg_session_factory, "FAILED", OLD)

    result = await _purge(pg_session_factory)

    assert result.deleted == 0
    assert await _statuses(pg_session_factory) == ["FAILED"]


async def test_pending_and_claimed_rows_are_untouched(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Both are live work. An old ``updated_at`` on a CLAIMED row means a
    long-running job, not a finished one."""

    await _insert(pg_session_factory, "PENDING", OLD)
    await _insert(pg_session_factory, "CLAIMED", OLD)

    result = await _purge(pg_session_factory)

    assert result.deleted == 0
    assert await _statuses(pg_session_factory) == ["CLAIMED", "PENDING"]


async def test_only_the_expired_done_rows_go(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _insert(pg_session_factory, "DONE", OLD, count=4)
    await _insert(pg_session_factory, "DONE", RECENT)
    await _insert(pg_session_factory, "FAILED", OLD)
    await _insert(pg_session_factory, "PENDING", OLD)

    result = await _purge(pg_session_factory)

    assert result.deleted == 4
    assert await _statuses(pg_session_factory) == ["DONE", "FAILED", "PENDING"]


async def test_one_run_deletes_across_several_batches(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The delete is batched so no single statement rewrites the table, but a
    run must still drain what it set out to — one batch is not one run."""

    await _insert(pg_session_factory, "DONE", OLD, count=7)

    result = await _purge(pg_session_factory, batch_size=2)

    assert result.deleted == 7
    assert result.capped is False
    assert await _count(pg_session_factory) == 0


async def test_the_per_run_cap_leaves_the_rest_for_the_next_run(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A large pre-existing backlog must not turn one daily maintenance job
    into an unbounded one. It drains over successive runs instead."""

    await _insert(pg_session_factory, "DONE", OLD, count=10)

    result = await _purge(pg_session_factory, batch_size=2, max_rows_per_run=6)

    assert result.deleted == 6
    assert result.capped is True
    assert await _count(pg_session_factory) == 4

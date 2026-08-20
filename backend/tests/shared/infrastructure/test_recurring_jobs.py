"""``RecurringJobSeeder`` — integration against a real PostgreSQL queue.

Seeding is the one operation that runs on every worker start, forever. Getting
it wrong in either direction is silent: seed too eagerly and the chains double
on each restart until the queue is saturated, seed too cautiously and a dead
chain never comes back.
"""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.shared.infrastructure.recurring_jobs import (
    RECURRING_KINDS,
    RecurringJobSeeder,
)

pytestmark = pytest.mark.integration


async def _seed(factory: async_sessionmaker[AsyncSession]) -> list[JobKind]:
    async with factory() as session:
        return await RecurringJobSeeder(session, PostgresJobQueue(session)).seed()


async def _count(factory: async_sessionmaker[AsyncSession], kind: JobKind) -> int:
    async with factory() as session:
        result = await session.execute(
            select(func.count()).select_from(JobRow).where(JobRow.kind == kind.value)
        )
        return int(result.scalar_one())


async def _set_status(
    factory: async_sessionmaker[AsyncSession], kind: JobKind, status: str
) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE jobs SET status = :status WHERE kind = :kind"),
            {"status": status, "kind": kind.value},
        )
        await session.commit()


async def test_a_first_start_seeds_every_recurring_chain(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await _seed(pg_session_factory)

    assert set(seeded) == set(RECURRING_KINDS)
    for kind in RECURRING_KINDS:
        assert await _count(pg_session_factory, kind) == 1


async def test_a_restart_does_not_fork_a_live_chain(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two live chains means two sweepers and two balance syncs, and the count
    doubles on every subsequent restart."""
    await _seed(pg_session_factory)

    seeded_again = await _seed(pg_session_factory)

    assert seeded_again == []
    for kind in RECURRING_KINDS:
        assert await _count(pg_session_factory, kind) == 1


async def test_a_chain_being_worked_on_counts_as_alive(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A CLAIMED job is held by a live worker. ``claim()`` never commits, so a
    crashed worker's row rolls back to PENDING on its own."""
    await _seed(pg_session_factory)
    await _set_status(pg_session_factory, JobKind.BALANCE_SYNC, "CLAIMED")

    seeded_again = await _seed(pg_session_factory)

    assert JobKind.BALANCE_SYNC not in seeded_again
    assert await _count(pg_session_factory, JobKind.BALANCE_SYNC) == 1


async def test_a_chain_that_exhausted_its_retries_is_revived(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """FAILED means the chain is over and nothing is scheduled. Restarting the
    worker is the documented recovery, so seeding must notice."""
    await _seed(pg_session_factory)
    await _set_status(pg_session_factory, JobKind.BALANCE_SYNC, "FAILED")

    seeded_again = await _seed(pg_session_factory)

    assert seeded_again == [JobKind.BALANCE_SYNC]
    assert await _count(pg_session_factory, JobKind.BALANCE_SYNC) == 2


async def test_a_completed_seed_job_alone_does_not_block_reseeding(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The DONE row is history. What keeps a chain alive is its successor, so
    a chain whose only job is DONE has stopped and must be seeded again.

    This is why ``dedupe_key`` is not the mechanism: its unique index spans the
    whole table for all time and would make this case unrecoverable."""
    await _seed(pg_session_factory)
    await _set_status(pg_session_factory, JobKind.RESERVATION_SWEEP, "DONE")

    seeded_again = await _seed(pg_session_factory)

    assert seeded_again == [JobKind.RESERVATION_SWEEP]


async def test_only_the_requested_kinds_are_seeded(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await _seed_kinds(pg_session_factory, [JobKind.BALANCE_SYNC])

    assert seeded == [JobKind.BALANCE_SYNC]
    assert await _count(pg_session_factory, JobKind.RESERVATION_SWEEP) == 0


async def _seed_kinds(
    factory: async_sessionmaker[AsyncSession], kinds: list[JobKind]
) -> list[JobKind]:
    async with factory() as session:
        return await RecurringJobSeeder(session, PostgresJobQueue(session)).seed(kinds)


async def test_a_seeded_job_is_immediately_claimable(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A chain that starts an interval late on every worker restart drifts.
    The seed job carries no ``run_after``, so it is due now."""
    await _seed_kinds(pg_session_factory, [JobKind.BALANCE_SYNC])

    async with pg_session_factory() as session:
        claimed = await PostgresJobQueue(session).claim()

    assert claimed is not None
    assert claimed.kind is JobKind.BALANCE_SYNC

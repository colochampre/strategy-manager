"""Real-Postgres proof of two ``UpdateStrategy`` guarantees that a fake
repository cannot exercise (tasks.md 2d.3, atomicity requirement;
design.md § 9):

1. ``get_by_id_for_update``'s ``SELECT ... FOR UPDATE`` lock serializes two
   concurrent toggles of the SAME strategy row, so they cannot both read
   the pre-toggle ``enabled`` value and both append an "enabled" event.
2. The event append and the ``enabled`` write commit or roll back together
   -- a failure appending the event must leave ``enabled`` unchanged.

Placed under ``infrastructure/`` (not ``application/``, where the fake-based
tests for this use case otherwise live) to reuse
``tests/strategies/infrastructure/conftest.py``'s real-Postgres fixtures --
the same convention ``AllocateCapital``'s own concurrency tests follow
(``tests/allocation/infrastructure/test_concurrency_race.py``). Deviation
from tasks.md's literal ``test_update_strategy.py`` path, noted in the
apply-progress report.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.update_strategy import (
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.domain.strategy import Strategy
from strategy_manager.strategies.infrastructure.enablement_log import (
    SqlAlchemyEnablementLog,
    StrategyEnablementEventRow,
)
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.repository import (
    SqlAlchemyStrategyRepository,
)

pytestmark = pytest.mark.integration

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}


async def _insert_strategy(
    session_factory: async_sessionmaker[AsyncSession], strategy_id: UUID, *, enabled: bool
) -> None:
    async with session_factory() as session:
        session.add(
            StrategyRow(
                id=strategy_id,
                name=f"strategy-{strategy_id}",
                enabled=enabled,
                fill_mode="PARTIAL",
                **_POOL,
            )
        )
        await session.commit()


async def _event_count(
    session_factory: async_sessionmaker[AsyncSession], strategy_id: UUID
) -> int:
    async with session_factory() as session:
        result = await session.execute(
            select(StrategyEnablementEventRow).where(
                StrategyEnablementEventRow.strategy_id == strategy_id
            )
        )
        return len(result.scalars().all())


class _PausingRepository:
    """Wraps the real repository. After ``get_by_id_for_update`` actually
    acquires the row lock, it waits for an external signal before
    returning -- keeping the lock held open long enough for the test to
    deterministically prove a SECOND transaction genuinely blocks on it,
    rather than hoping asyncio's scheduler happens to interleave two bare
    coroutines the "right" way."""

    def __init__(self, inner: SqlAlchemyStrategyRepository, resume: asyncio.Event) -> None:
        self._inner = inner
        self._resume = resume

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        return await self._inner.get_by_id(strategy_id)

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        result = await self._inner.get_by_id_for_update(strategy_id)
        await self._resume.wait()
        return result

    async def insert(self, strategy: Strategy) -> None:  # pragma: no cover -- unused here
        await self._inner.insert(strategy)

    async def list_all(self) -> list[Strategy]:  # pragma: no cover -- unused here
        return await self._inner.list_all()

    async def update(self, strategy: Strategy) -> None:
        await self._inner.update(strategy)


async def test_update_strategy_takes_for_update_lock_on_strategy_row(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two concurrent toggles of the SAME strategy, both from disabled to
    enabled, must not both read ``enabled=False`` and both append an
    "enabled" event. Proven in two parts:

    (1) While transaction A holds the row lock open (paused right after
        acquiring it, via ``_PausingRepository``), transaction B's own
        ``get_by_id_for_update`` on the SAME row is still pending after a
        real wait -- this is the DETERMINISTIC part: it proves the lock
        genuinely blocks a second reader, not merely that one particular
        asyncio schedule happened to interleave correctly.
    (2) Once A finishes its full ``update()`` and commits (releasing the
        lock), B unblocks, re-reads the now-``enabled=True`` row, and --
        because nothing changed from B's point of view -- writes no second
        event. Exactly one event exists at the end.
    """
    strategy_id = uuid4()
    await _insert_strategy(pg_session_factory, strategy_id, enabled=False)

    resume_a = asyncio.Event()

    async def toggle_on_a() -> None:
        async with pg_session_factory() as session:
            use_case = UpdateStrategy(
                repository=_PausingRepository(
                    SqlAlchemyStrategyRepository(session), resume_a
                ),  # type: ignore[arg-type]
                commit=session,  # type: ignore[arg-type]
                enablement_log=SqlAlchemyEnablementLog(session),
                clock=SystemClock(),
            )
            await use_case.update(UpdateCommand(strategy_id=strategy_id, enabled=True))

    async def toggle_on_b() -> None:
        async with pg_session_factory() as session:
            use_case = UpdateStrategy(
                repository=SqlAlchemyStrategyRepository(session),
                commit=session,  # type: ignore[arg-type]
                enablement_log=SqlAlchemyEnablementLog(session),
                clock=SystemClock(),
            )
            await use_case.update(UpdateCommand(strategy_id=strategy_id, enabled=True))

    task_a = asyncio.create_task(toggle_on_a())
    await asyncio.sleep(0.2)  # let A reach and hold the lock, paused on resume_a

    task_b = asyncio.create_task(toggle_on_b())
    await asyncio.sleep(0.3)  # B should now be genuinely blocked on the SAME row lock
    assert not task_b.done(), "B completed without waiting for A's held row lock"

    resume_a.set()  # let A finish (write + event + commit), releasing the lock
    await asyncio.gather(task_a, task_b)

    assert await _event_count(pg_session_factory, strategy_id) == 1


class _RaisingEnablementLog:
    """Fails the event append deliberately, so the surrounding transaction
    is observed rolling back the ALREADY-FLUSHED ``enabled`` write too."""

    async def append(self, *_: object, **__: object) -> None:
        raise RuntimeError("simulated event append failure")


async def test_event_append_failure_rolls_back_the_enabled_write_too(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Atomicity requirement: the event row and the ``enabled`` write commit
    or roll back together. Uses a REAL repository sharing a REAL session (so
    the ``enabled`` write genuinely flushes into an open transaction) and a
    fake log that raises before ``commit()`` is ever reached -- proving the
    flushed-but-uncommitted write never becomes visible to another
    connection."""
    strategy_id = uuid4()
    await _insert_strategy(pg_session_factory, strategy_id, enabled=False)

    async with pg_session_factory() as session:
        use_case = UpdateStrategy(
            repository=SqlAlchemyStrategyRepository(session),
            commit=session,  # type: ignore[arg-type]
            enablement_log=_RaisingEnablementLog(),
            clock=SystemClock(),
        )
        with pytest.raises(RuntimeError, match="simulated event append failure"):
            await use_case.update(UpdateCommand(strategy_id=strategy_id, enabled=True))
        await session.rollback()

    async with pg_session_factory() as verify_session:
        row = await verify_session.get(StrategyRow, strategy_id)
        assert row is not None
        assert row.enabled is False  # unchanged: the write was never committed

    assert await _event_count(pg_session_factory, strategy_id) == 0

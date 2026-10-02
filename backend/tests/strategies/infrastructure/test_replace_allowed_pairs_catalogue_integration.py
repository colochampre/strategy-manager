"""Real-PostgreSQL proof that ``ReplaceAllowedPairs`` makes its venue call BEFORE
the strategy row lock and never under it (decision 41, design addendum § E and
§ K; tasks.md 9vc.6; ``rules.tasks``: a lock has no meaningful fake).

**Why this needs a real database.** The property is "no venue call runs while the
row lock is held", and a fake repository can be made to satisfy any lock claim by
construction. Here the repository is the real one, the catalogue is a fake that
PARKS inside ``available_pairs`` on an ``asyncio.Event``, and a second connection
tries the very lock the use case takes.

**Deterministic, not scheduler luck.** No test waits on ``sleep(0)`` or on a
barrier that unlocked code would also pass. The parked catalogue signals
``entered`` once the use case is genuinely inside the venue call, so the test acts
on a known state. The waiting test asserts ``not task.done()`` AND polls
``pg_locks`` until the replace is seen waiting on the row, so "still pending" can
never be mistaken for "not started yet".

Spelling across the boundary: the venue lists ``STXUSDT``, the request sends
``STXUSDT_PERP``, the stored form is ``STXUSDT``.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.application.replace_allowed_pairs import (
    ReplaceAllowedPairs,
    ReplaceAllowedPairsCommand,
)
from strategy_manager.strategies.domain.pair_catalog import PairsChangedConcurrently
from strategy_manager.strategies.domain.strategy import Strategy
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository

pytestmark = pytest.mark.integration

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}
_WAIT = 5.0  # seconds; only ever a ceiling for a hung test, never a pacing delay


class _ParkingCatalog:
    """A fake ``PairCatalogPort`` that parks inside ``available_pairs`` until the
    test lets it go. ``entered`` is set the moment the use case is in the call."""

    def __init__(self, available: frozenset[str]) -> None:
        self.available = available
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.asked: list[PoolKey] = []

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.asked.append(pool)
        self.entered.set()
        await self.release.wait()
        return self.available


async def _seed(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    pairs: list[str],
    *,
    enabled: bool = False,
) -> None:
    async with factory() as session:
        session.add(
            StrategyRow(
                id=strategy_id,
                name=f"strategy-{strategy_id}",
                enabled=enabled,
                fill_mode="PARTIAL",
                allowed_pairs=pairs,
                **_POOL,
            )
        )
        await session.commit()


async def _row(factory: async_sessionmaker[AsyncSession], strategy_id: UUID) -> StrategyRow:
    async with factory() as session:
        row = await session.get(StrategyRow, strategy_id)
        assert row is not None
        return row


async def _replace(
    factory: async_sessionmaker[AsyncSession],
    catalog: _ParkingCatalog,
    strategy_id: UUID,
    pairs: list[str],
) -> Strategy:
    async with factory() as session:
        use_case = ReplaceAllowedPairs(
            repository=SqlAlchemyStrategyRepository(session),
            pairs=catalog,
            commit=session,  # type: ignore[arg-type]
        )
        return await use_case.replace(ReplaceAllowedPairsCommand(strategy_id, pairs))


@contextlib.asynccontextmanager
async def _running(
    catalog: _ParkingCatalog,
    task: "asyncio.Task[Strategy]",
    holder: AsyncSession | None = None,
) -> AsyncIterator[None]:
    """Whatever the test does, let the parked catalogue go, release the holder's
    lock and reap the task, so a failed assertion fails the test instead of
    hanging it or leaving a transaction open for the next test's TRUNCATE. The
    holder is released BEFORE the task is reaped: a task blocked on that lock can
    only be cancelled once the lock is gone."""
    try:
        yield
    finally:
        catalog.release.set()
        if holder is not None:
            await holder.rollback()
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(task, _WAIT)


async def _wait_until_parked(catalog: _ParkingCatalog) -> None:
    try:
        await asyncio.wait_for(catalog.entered.wait(), _WAIT)
    except TimeoutError:
        pytest.fail("the replace never reached the catalogue call")


async def _is_waiting_on_a_strategy_row_lock(
    factory: async_sessionmaker[AsyncSession],
) -> bool:
    """Whether some backend is blocked, in pg_locks, behind another transaction on
    the ``SELECT ... FOR UPDATE`` of ``strategies``."""
    async with factory() as session:
        waiting = await session.scalar(
            text(
                "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                "WHERE NOT l.granted AND l.locktype IN ('transactionid', 'tuple') "
                "AND a.pid <> pg_backend_pid() "
                "AND a.query ILIKE '%FROM strategies%FOR UPDATE%'"
            )
        )
    return bool(waiting)


async def test_the_strategy_row_is_lockable_by_another_transaction_while_the_catalogue_read_is_in_flight(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """While the replace is parked inside ``available_pairs`` a second connection
    takes ``SELECT ... FOR UPDATE NOWAIT`` on the same row and succeeds: the venue
    read holds no row lock. ``NOWAIT`` makes a held lock an error instead of a
    wait, so a regression fails loudly rather than hanging.

    Mutation (observed): moving the catalogue call after ``get_by_id_for_update``
    makes the ``NOWAIT`` raise ``LockNotAvailable``."""
    strategy_id = uuid4()
    await _seed(pg_session_factory, strategy_id, ["ETHUSDT"])
    catalog = _ParkingCatalog(frozenset({"STXUSDT"}))

    task = asyncio.create_task(
        _replace(pg_session_factory, catalog, strategy_id, ["ETHUSDT", "STXUSDT_PERP"])
    )
    async with _running(catalog, task):
        await _wait_until_parked(catalog)

        async with pg_session_factory() as other:
            try:
                await other.execute(
                    text("SELECT id FROM strategies WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": strategy_id},
                )
            except DBAPIError as exc:  # pragma: no cover - only on a regression
                pytest.fail(f"the row was locked while the venue read was in flight: {exc!r}")
            await other.rollback()

        catalog.release.set()
        updated = await asyncio.wait_for(task, _WAIT)

    assert updated.allowed_pairs.sorted() == ["ETHUSDT", "STXUSDT"]
    assert (await _row(pg_session_factory, strategy_id)).allowed_pairs == ["ETHUSDT", "STXUSDT"]
    assert catalog.asked == [("pionex", "spot", "USDT")]


async def test_replace_waits_for_a_held_row_lock_after_its_catalogue_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A holder keeps the row locked in an open transaction. The replace is let
    past its catalogue call and must WAIT on the lock, not run through it. The
    holder then commits a changed ``enabled``; the replace completes with the row
    it re-read under the lock, and its write does not revert ``enabled``."""
    strategy_id = uuid4()
    await _seed(pg_session_factory, strategy_id, ["ETHUSDT"], enabled=False)
    catalog = _ParkingCatalog(frozenset({"STXUSDT"}))

    async with pg_session_factory() as holder:
        await SqlAlchemyStrategyRepository(holder).get_by_id_for_update(strategy_id)

        task = asyncio.create_task(
            _replace(pg_session_factory, catalog, strategy_id, ["ETHUSDT", "STXUSDT_PERP"])
        )
        async with _running(catalog, task, holder):
            await _wait_until_parked(catalog)
            # The venue read ran WHILE the holder owned the lock, so the replace
            # holds none: it can only be waiting for one it does not yet have.
            catalog.release.set()

            deadline = asyncio.get_running_loop().time() + _WAIT
            while not await _is_waiting_on_a_strategy_row_lock(pg_session_factory):
                assert asyncio.get_running_loop().time() < deadline, (
                    "the replace never showed as waiting on the strategy row in pg_locks"
                )
                await asyncio.sleep(0.05)
            assert not task.done(), "the replace completed without waiting for the held row lock"

            await holder.execute(
                text("UPDATE strategies SET enabled = true WHERE id = :id"), {"id": strategy_id}
            )
            await holder.commit()  # releases the lock

            updated = await asyncio.wait_for(task, _WAIT)

    row = await _row(pg_session_factory, strategy_id)
    assert row.allowed_pairs == ["ETHUSDT", "STXUSDT"]
    assert row.enabled is True  # the holder's change survived the replace
    assert updated.enabled is True  # and the replace answered with the row it re-read


async def test_the_row_lock_read_refreshes_a_row_the_session_already_holds(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``ReplaceAllowedPairs`` now reads the strategy twice in ONE session: unlocked,
    then under ``FOR UPDATE``. The re-check is only worth anything if the second
    read returns what the database holds NOW. A plain ``SELECT ... FOR UPDATE``
    hands back an ORM row the session still references with its OLD values, so the
    row is held here on purpose: the identity map is weak, and without a strong
    reference the unlocked read is garbage-collected and the bug hides."""
    strategy_id = uuid4()
    await _seed(pg_session_factory, strategy_id, ["ETHUSDT"])

    async with pg_session_factory() as session:
        held = await session.get(StrategyRow, strategy_id)
        assert held is not None  # strong reference: it stays in the identity map

        async with pg_session_factory() as other:
            await other.execute(
                text("UPDATE strategies SET allowed_pairs = ARRAY['SOLUSDT'] WHERE id = :id"),
                {"id": strategy_id},
            )
            await other.commit()

        locked = await SqlAlchemyStrategyRepository(session).get_by_id_for_update(strategy_id)

    assert locked is not None
    assert locked.allowed_pairs.sorted() == ["SOLUSDT"]


async def test_a_concurrent_removal_of_a_requested_pair_refuses_with_pairs_changed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Stored ``{ETHUSDT, SFPUSDT}``; the request keeps both and adds ``STXUSDT``,
    so only ``STXUSDT`` is validated. While the replace is parked another
    transaction stores ``{ETHUSDT}`` and commits (it can: the replace holds no
    lock). Under the lock ``SFPUSDT`` would be an addition nobody checked, so the
    save is refused and the row keeps what the other transaction wrote."""
    strategy_id = uuid4()
    await _seed(pg_session_factory, strategy_id, ["ETHUSDT", "SFPUSDT"])
    catalog = _ParkingCatalog(frozenset({"STXUSDT"}))

    task = asyncio.create_task(
        _replace(
            pg_session_factory, catalog, strategy_id, ["ETHUSDT", "SFPUSDT", "STXUSDT_PERP"]
        )
    )
    async with _running(catalog, task):
        await _wait_until_parked(catalog)

        async with pg_session_factory() as other:
            # A ceiling, so a replace that wrongly holds the row lock FAILS this
            # write instead of deadlocking the test against its own parked task.
            await other.execute(text("SET LOCAL lock_timeout = '2000ms'"))
            await other.execute(
                text("UPDATE strategies SET allowed_pairs = ARRAY['ETHUSDT'] WHERE id = :id"),
                {"id": strategy_id},
            )
            await other.commit()

        catalog.release.set()
        with pytest.raises(PairsChangedConcurrently):
            await asyncio.wait_for(task, _WAIT)

    assert (await _row(pg_session_factory, strategy_id)).allowed_pairs == ["ETHUSDT"]

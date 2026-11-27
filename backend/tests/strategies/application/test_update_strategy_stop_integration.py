"""A stop widened under seats above its new cap, on real PostgreSQL (panel-redesign
RD.9a, owner decisions L58, L59, L68).

``UpdateStrategy`` lowers every ACTIVE seat above ``max_leverage(new stop)`` to that
cap in the stop's own transaction, under every subscriber's pool lock, the strategy row
and then the seat rows, and records one event per lowered seat. A stop that raises the
cap or leaves it, a seat at or below the cap, a seat that is leaving and one that has
ended are left as they were.

The lock is proven the way ``test_archive_vs_allocate_concurrency.py`` proves archive's:
a transaction holds the subscriber's pool lock through the key ``AllocateCapital`` takes
(``LockKey.from_pool_key``), and the stop change must still be waiting
(``not task.done()``) after a real wait.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.update_strategy import UpdateCommand, UpdateStrategy
from strategy_manager.strategies.domain.stop_loss import StopLossPct
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from strategy_manager.subscriptions.infrastructure.models import (
    LeverageLoweredRow,
    SubscriptionRow,
)
from tests.owner import ensure_author_subscription
from tests.strategies.author_names import FixedAuthorNames
from tests.strategies.wiring import real_subscribers
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
FIXED_NOW = datetime(2026, 11, 27, 12, 0, 0, tzinfo=UTC)
LOGGER = "strategy_manager.strategies.application.update_strategy"
POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)


class _Clock:
    def now(self) -> datetime:
        return FIXED_NOW


class _FailingCommit:
    """A commit that fails: everything the use case wrote is then rolled back."""

    async def commit(self) -> None:
        raise RuntimeError("the commit failed")


def _update(session: AsyncSession, *, commit: object | None = None) -> UpdateStrategy:
    ledger = SqlAlchemyLedgerRepository(session)
    return UpdateStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        commit=commit if commit is not None else session,  # type: ignore[arg-type]
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=_Clock(),
        author_names=FixedAuthorNames(),
        pool_lock=PoolLockAdapter(session),
        subscribers=real_subscribers(session),
        exposure=StrategyExposureAdapter(
            ledger=ledger,
            symbol_holdings=ReadSymbolHoldings(ledger),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
    )


async def _change_stop(
    factory: Factory, strategy_id: UUID, level: str, *, commit: object | None = None
) -> None:
    async with factory() as session:
        await _update(session, commit=commit).update(
            UpdateCommand(strategy_id=strategy_id, stop_loss_pct=StopLossPct(Decimal(level)))
        )


class Seats:
    """A strategy at a 10 percent stop (a cap of 9x) and the seats on it, by name."""

    def __init__(self, factory: Factory, strategy_id: UUID) -> None:
        self.factory = factory
        self.strategy_id = strategy_id
        self.seat: dict[str, UUID] = {}
        self.owner: dict[str, UUID] = {}

    async def add(self, name: str, leverage: int, status: str = "ACTIVE") -> None:
        user_id, pool_id = await seeds.user(self.factory)
        assert pool_id is not None
        self.owner[name] = user_id
        self.seat[name] = await seeds.subscription(
            self.factory, user_id, self.strategy_id, pool_id, status=status, leverage=leverage
        )

    async def leverages(self) -> dict[str, int]:
        async with self.factory() as session:
            rows = await session.execute(
                select(SubscriptionRow.id, SubscriptionRow.leverage).where(
                    SubscriptionRow.strategy_id == self.strategy_id
                )
            )
            by_id = {seat_id: leverage for seat_id, leverage in rows.all()}
        return {name: by_id[seat_id] for name, seat_id in self.seat.items()}


async def _seats(factory: Factory) -> Seats:
    strategy_id = await seeds.strategy(factory, stop_loss_pct="10")
    async with factory() as session:
        await ensure_author_subscription(session, strategy_id)
        await session.commit()
    seats = Seats(factory, strategy_id)
    await seats.add("above", 9)
    await seats.add("middle", 5)
    await seats.add("at_new_cap", 4)
    await seats.add("below", 2)
    await seats.add("leaving", 12, status="LEAVING")
    await seats.add("ended", 15, status="ENDED")
    return seats


async def _events(factory: Factory) -> list[LeverageLoweredRow]:
    async with factory() as session:
        result = await session.execute(
            select(LeverageLoweredRow).order_by(LeverageLoweredRow.old_leverage)
        )
        return list(result.scalars().all())


async def _stop_of(factory: Factory, strategy_id: UUID) -> Decimal:
    async with factory() as session:
        row = await session.get(StrategyRow, strategy_id)
        assert row is not None
        return Decimal(row.stop_loss_pct)


async def test_a_widened_stop_lowers_exactly_the_seats_above_its_cap_to_the_cap(
    pg_session_factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    seats = await _seats(pg_session_factory)

    with caplog.at_level("INFO", logger=LOGGER):
        # 100 / (20 + 1) is 4.76: a cap of 4x.
        await _change_stop(pg_session_factory, seats.strategy_id, "20")

    assert await seats.leverages() == {
        "above": 4,
        "middle": 4,
        "at_new_cap": 4,
        "below": 2,
        "leaving": 12,  # a seat that is leaving opens nothing
        "ended": 15,
    }
    assert await _stop_of(pg_session_factory, seats.strategy_id) == Decimal("20")
    events = await _events(pg_session_factory)
    assert [
        (e.user_id, e.strategy_id, e.subscription_id, e.old_leverage, e.new_leverage, e.occurred_at)
        for e in events
    ] == [
        (seats.owner["middle"], seats.strategy_id, seats.seat["middle"], 5, 4, FIXED_NOW),
        (seats.owner["above"], seats.strategy_id, seats.seat["above"], 9, 4, FIXED_NOW),
    ]
    [line] = [r.getMessage() for r in caplog.records if "stop level changed" in r.getMessage()]
    assert "seats_lowered=2" in line


@pytest.mark.parametrize("level", ["5", "9.5", "10"])
async def test_a_stop_that_raises_the_cap_or_leaves_it_touches_no_seat(
    pg_session_factory: Factory, level: str
) -> None:
    seats = await _seats(pg_session_factory)
    # A seat left above the CURRENT cap before this rule existed: a stop that does not
    # lower the cap is not the occasion to lower it.
    await seats.add("legacy", 12)
    before = await seats.leverages()

    # 5 percent is a cap of 16x; 9.5 is 9x again (100 / 10.5); 10 is unchanged.
    await _change_stop(pg_session_factory, seats.strategy_id, level)

    assert await seats.leverages() == before
    assert await _events(pg_session_factory) == []
    assert await _stop_of(pg_session_factory, seats.strategy_id) == Decimal(level)


async def test_a_stop_change_that_lowers_no_seat_still_changes_the_stop(
    pg_session_factory: Factory,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory, stop_loss_pct="10")
    async with pg_session_factory() as session:
        await ensure_author_subscription(session, strategy_id)
        await session.commit()

    await _change_stop(pg_session_factory, strategy_id, "20")

    # The author's own seat starts at one times: nothing is above the cap.
    assert await _stop_of(pg_session_factory, strategy_id) == Decimal("20")
    assert await _events(pg_session_factory) == []


async def test_a_failure_before_the_commit_leaves_the_stop_the_seats_and_the_events_as_they_were(
    pg_session_factory: Factory,
) -> None:
    seats = await _seats(pg_session_factory)
    before = await seats.leverages()

    with pytest.raises(RuntimeError):
        await _change_stop(pg_session_factory, seats.strategy_id, "20", commit=_FailingCommit())

    assert await seats.leverages() == before
    assert await _events(pg_session_factory) == []
    assert await _stop_of(pg_session_factory, seats.strategy_id) == Decimal("10")


async def test_a_stop_change_waits_for_a_subscribers_pool_lock(
    pg_session_factory: Factory,
) -> None:
    """A subscriber's allocation holds the pool's advisory lock (the key
    ``AllocateCapital`` takes); the stop change has to wait for it and then lowers
    the seat."""
    seats = await _seats(pg_session_factory)
    holder_has_lock = asyncio.Event()
    release = asyncio.Event()

    async def hold_the_pool_lock() -> None:
        async with pg_session_factory() as session:
            await PgAdvisoryLockAdapter(session).acquire(
                LockKey.from_pool_key(seats.owner["above"], POOL)
            )
            holder_has_lock.set()
            await release.wait()
            await session.commit()

    holder = asyncio.create_task(hold_the_pool_lock())
    await holder_has_lock.wait()

    change = asyncio.create_task(_change_stop(pg_session_factory, seats.strategy_id, "20"))
    await asyncio.sleep(0.3)
    assert not change.done(), (
        "the stop change finished without waiting for a subscriber's held pool lock"
    )
    assert (await seats.leverages())["above"] == 9  # nothing was written meanwhile

    release.set()
    await asyncio.gather(holder, change)

    assert (await seats.leverages())["above"] == 4
    assert await _stop_of(pg_session_factory, seats.strategy_id) == Decimal("20")


async def test_a_request_that_names_no_stop_does_not_wait_for_a_subscribers_pool_lock(
    pg_session_factory: Factory,
) -> None:
    """Existing behaviour: a rename takes no subscriber's lock, so it does not wait
    for one."""
    seats = await _seats(pg_session_factory)
    holder_has_lock = asyncio.Event()
    release = asyncio.Event()

    async def hold_the_pool_lock() -> None:
        async with pg_session_factory() as session:
            await PgAdvisoryLockAdapter(session).acquire(
                LockKey.from_pool_key(seats.owner["above"], POOL)
            )
            holder_has_lock.set()
            await release.wait()
            await session.commit()

    holder = asyncio.create_task(hold_the_pool_lock())
    await holder_has_lock.wait()
    try:
        async with pg_session_factory() as session:
            await asyncio.wait_for(
                _update(session).update(UpdateCommand(strategy_id=seats.strategy_id, name="new")),
                timeout=5,
            )
    finally:
        release.set()
        await holder

    async with pg_session_factory() as session:
        name = (
            await session.execute(
                text("SELECT name FROM strategies WHERE id = :id"), {"id": seats.strategy_id}
            )
        ).scalar_one()
    assert name == "new"

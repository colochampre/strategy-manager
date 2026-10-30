"""The mode an opening runs in, on real PostgreSQL (multi-user design AD7;
decisions 6, 14 and 26; tasks.md E.4).

``AllocateCapital`` reads the user's mode through ``SqlAlchemyUserMode``, inside the
pool advisory lock, and records the result on the reservation. A reservation only
reduces what a later allocation of the SAME mode can be granted. The user row is
read ``FOR SHARE``, so a flip of the mode (which takes the row ``FOR UPDATE``)
cannot interleave with an opening: the lock-hold test proves the opening waits.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
)
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.allocation.infrastructure.user_mode import SqlAlchemyUserMode
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.fakes import AlwaysEnabledPool, RecordingSkipRecorder
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy
from tests.owner import OWNER_ID, allocate_command, seed_reservation_row

pytestmark = pytest.mark.integration

WAIT_SECONDS = 5.0
MARKET = ("pionex", "spot", "USDT")
POOLS = {
    (OWNER_ID, MARKET): PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        user_id=OWNER_ID,
        min_order_size=Decimal("10"),
    )
}


@pytest.fixture(autouse=True)
async def _owner_back_to_the_default_mode(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[None]:
    """``users`` outlives a fixture's truncate, so a test that moves the owner's
    mode must put it back: the default every other test assumes."""
    yield
    await _set_user_mode(pg_session_factory, OWNER_ID, Mode.SIMULATION)


async def _set_user_mode(
    factory: async_sessionmaker[AsyncSession], user_id: UUID, mode: Mode
) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE users SET mode = :mode WHERE id = :id"),
            {"mode": mode.value, "id": user_id},
        )
        await session.commit()


async def _allocate(
    factory: async_sessionmaker[AsyncSession], command: AllocateCommand, *, brake: bool = False
) -> AllocationResult:
    source = FakeBalanceSource()
    source.set_balance(*MARKET, Decimal("1000"))
    async with factory() as session:
        use_case = AllocateCapital(
            strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
            pool_balance=PoolBalanceAdapter(POOLS, source),
            lock=PgAdvisoryLockAdapter(session),
            reservations=SqlAlchemyReservationRepository(session),
            commit=session,
            clock=SystemClock(),
            reservation_ttl_seconds=30,
            skip_recorder=RecordingSkipRecorder(),
            pool_status=AlwaysEnabledPool(),
            user_mode=SqlAlchemyUserMode(session, brake=brake),
        )
        return await use_case.allocate(command)


async def _opening(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID, amount: str = "200"
) -> AllocateCommand:
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    return await allocate_command(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        requested=Money(amount=Decimal(amount), currency=Currency.USDT),
    )


async def _holding(
    factory: async_sessionmaker[AsyncSession], strategy_id: UUID, *, mode: Mode, amount: str
) -> None:
    """An ACTIVE reservation of the owner on the market, in ``mode``."""
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    async with factory() as session:
        await seed_reservation_row(
            session,
            reservation_id=uuid4(),
            strategy_id=strategy_id,
            signal_id=signal_id,
            market=MARKET,
            amount=Decimal(amount),
            status="PENDING",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            mode=mode.value,
        )
        await session.commit()


async def _mode_of(factory: async_sessionmaker[AsyncSession], signal_id: UUID) -> str:
    async with factory() as session:
        return (
            await session.execute(
                select(ReservationRow.mode).where(ReservationRow.signal_id == signal_id)
            )
        ).scalar_one()


@pytest.mark.parametrize(
    ("user_mode", "brake", "expected"),
    [
        (Mode.LIVE, False, Mode.LIVE),
        (Mode.SIMULATION, False, Mode.SIMULATION),
        (Mode.LIVE, True, Mode.SIMULATION),
    ],
)
async def test_the_reservation_records_the_users_mode_under_the_brake(
    pg_session_factory: async_sessionmaker[AsyncSession],
    user_mode: Mode,
    brake: bool,
    expected: Mode,
) -> None:
    """LIVE only with the brake off and the user LIVE (decisions 6 and 14)."""
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _set_user_mode(pg_session_factory, OWNER_ID, user_mode)
    command = await _opening(pg_session_factory, strategy_id)

    result = await _allocate(pg_session_factory, command, brake=brake)

    assert result.outcome is DecisionOutcome.FULL
    assert await _mode_of(pg_session_factory, command.signal_id) == expected.value


@pytest.mark.parametrize(
    ("holding", "asking"),
    [(Mode.SIMULATION, Mode.LIVE), (Mode.LIVE, Mode.SIMULATION)],
)
async def test_a_reservation_of_the_other_mode_does_not_reduce_what_can_be_granted(
    pg_session_factory: async_sessionmaker[AsyncSession], holding: Mode, asking: Mode
) -> None:
    """Decision 26, both directions: 900 of the 1000 is held in the OTHER mode, so
    it holds no capital this allocation can use."""
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _holding(pg_session_factory, strategy_id, mode=holding, amount="900")
    await _set_user_mode(pg_session_factory, OWNER_ID, asking)
    command = await _opening(pg_session_factory, strategy_id)

    result = await _allocate(pg_session_factory, command)

    assert result.outcome is DecisionOutcome.FULL
    assert result.granted == Decimal("200")
    assert await _mode_of(pg_session_factory, command.signal_id) == asking.value


@pytest.mark.parametrize("mode", [Mode.LIVE, Mode.SIMULATION])
async def test_a_reservation_of_the_same_mode_still_reduces_what_can_be_granted(
    pg_session_factory: async_sessionmaker[AsyncSession], mode: Mode
) -> None:
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await _holding(pg_session_factory, strategy_id, mode=mode, amount="900")
    await _set_user_mode(pg_session_factory, OWNER_ID, mode)
    command = await _opening(pg_session_factory, strategy_id)

    result = await _allocate(pg_session_factory, command)

    assert result.outcome is DecisionOutcome.PARTIAL
    assert result.granted == Decimal("100")


async def _until_waiting_on_a_row_lock(factory: async_sessionmaker[AsyncSession]) -> None:
    """Polls until some backend is waiting for another transaction to end: a row
    lock that is not granted shows as a waiting ``transactionid`` lock."""
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while True:
        async with factory() as session:
            waiting = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE locktype = 'transactionid' AND NOT granted"
                    )
                )
            ).scalar_one()
        if waiting:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("no backend ever waited on a row lock")
        await asyncio.sleep(0.02)


async def test_an_opening_waits_for_a_flip_of_the_users_mode_and_then_runs_in_the_new_one(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A flip takes the user row ``FOR UPDATE``. The opening reads it ``FOR SHARE``,
    so it does not finish while the flip is open, and once the flip commits it
    reads the NEW mode: a real reservation never appears after the flat check."""
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _set_user_mode(factory, OWNER_ID, Mode.LIVE)
    command = await _opening(factory, strategy_id)

    task: asyncio.Task[AllocationResult] | None = None
    async with factory() as flip:
        await flip.execute(select(UserRow.id).where(UserRow.id == OWNER_ID).with_for_update())
        task = asyncio.create_task(_allocate(factory, command))
        try:
            await _until_waiting_on_a_row_lock(factory)
            assert not task.done(), "the opening finished while the flip held the user row"
            await flip.execute(
                text("UPDATE users SET mode = 'SIMULATION' WHERE id = :id"), {"id": OWNER_ID}
            )
            await flip.commit()
            result = await asyncio.wait_for(task, WAIT_SECONDS)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert result.outcome is DecisionOutcome.FULL
    assert await _mode_of(factory, command.signal_id) == Mode.SIMULATION.value

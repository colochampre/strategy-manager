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
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    VaultTradeCapabilityAdapter,
)
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
    ModeChangedError,
)
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.allocation_mode import (
    SqlAlchemyAllocationMode,
)
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.allocation.infrastructure.reservation_gateway import (
    ReservationGatewayAdapter,
)
from strategy_manager.allocation.infrastructure.user_mode import SqlAlchemyUserMode
from strategy_manager.execution.infrastructure.live_exposure import SqlAlchemyLiveExposure
from strategy_manager.identity.application.change_mode import (
    ChangeMode,
    ModeChangeRefusedError,
    ModeRefusal,
)
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.fakes import (
    ActiveSubscription,
    AlwaysEnabledPool,
    AnyKeyTrades,
    RecordingSkipRecorder,
)
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
    factory: async_sessionmaker[AsyncSession],
    command: AllocateCommand,
    *,
    brake: bool = False,
    held: "_HeldCommit | None" = None,
) -> AllocationResult:
    source = FakeBalanceSource()
    source.set_balance(*MARKET, Decimal("1000"))
    async with factory() as session:
        use_case = AllocateCapital(
            strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
            pool_balance=PoolBalanceAdapter(POOLS, source),
            lock=PgAdvisoryLockAdapter(session),
            reservations=SqlAlchemyReservationRepository(session),
            commit=session if held is None else held.on(session),
            clock=SystemClock(),
            reservation_ttl_seconds=30,
            skip_recorder=RecordingSkipRecorder(),
            pool_status=AlwaysEnabledPool(),
            user_mode=SqlAlchemyUserMode(session, brake=brake),
            trade_capability=AnyKeyTrades(),
            subscription_state=ActiveSubscription(),
        )
        return await use_case.allocate(command)


async def _opening(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    amount: str = "200",
    *,
    pre_checked_mode: Mode = Mode.LIVE,
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
        pre_checked_mode=pre_checked_mode,
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


async def _mode_of_user(factory: async_sessionmaker[AsyncSession], user_id: UUID) -> str:
    async with factory() as session:
        return (
            await session.execute(select(UserRow.mode).where(UserRow.id == user_id))
        ).scalar_one()


async def _reservations_of(
    factory: async_sessionmaker[AsyncSession], signal_id: UUID
) -> list[str]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(ReservationRow.mode).where(ReservationRow.signal_id == signal_id)
                )
            ).scalars()
        )


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

    result = await _allocate(
        pg_session_factory, replace(command, pre_checked_mode=expected), brake=brake
    )

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
    command = await _opening(pg_session_factory, strategy_id, pre_checked_mode=asking)

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
    command = await _opening(pg_session_factory, strategy_id, pre_checked_mode=mode)

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


async def test_an_opening_waits_for_a_flip_of_the_users_mode_and_reserves_nothing_real(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A flip takes the user row ``FOR UPDATE`` and the opening reads it ``FOR
    SHARE``, so the opening does not finish while the flip is open. Once the flip
    commits it reads the NEW mode, which is not the one its pre-checks went by: it
    reserves nothing, so a real reservation never appears after the flat check
    passed. The delivery then runs again, and that run is simulated."""
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _set_user_mode(factory, OWNER_ID, Mode.LIVE)
    command = await _opening(factory, strategy_id, pre_checked_mode=Mode.LIVE)

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
            with pytest.raises(ModeChangedError):
                await asyncio.wait_for(task, WAIT_SECONDS)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert await _reservations_of(factory, command.signal_id) == []

    await _allocate(factory, replace(command, pre_checked_mode=Mode.SIMULATION))

    assert await _reservations_of(factory, command.signal_id) == [Mode.SIMULATION.value]


class _HeldCommit:
    """Holds an opening at its commit, with its reservation written and its locks
    still held, until the test releases it."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.released = asyncio.Event()

    def on(self, session: AsyncSession) -> "_HeldCommitOn":
        return _HeldCommitOn(self, session)


class _HeldCommitOn:
    def __init__(self, held: _HeldCommit, session: AsyncSession) -> None:
        self._held = held
        self._session = session

    async def commit(self) -> None:
        self._held.reached.set()
        await self._held.released.wait()
        await self._session.commit()


async def _flip_to_simulation(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        await ChangeMode(
            SqlAlchemyUserRepository(session),
            VaultTradeCapabilityAdapter(session),
            SqlAlchemyLiveExposure(session),
            session,
            brake=False,
        ).execute(OWNER_ID, Mode.SIMULATION)


async def test_a_flip_to_simulation_waits_for_an_opening_in_flight_and_then_sees_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The other order of the race: the opening reached the lock first. The flip
    does not finish while the opening is open, and once it commits the flip finds
    the real reservation and refuses, naming its market."""
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _set_user_mode(factory, OWNER_ID, Mode.LIVE)
    command = await _opening(factory, strategy_id)
    held = _HeldCommit()

    opening = asyncio.create_task(_allocate(factory, command, held=held))
    await asyncio.wait_for(held.reached.wait(), WAIT_SECONDS)
    flip = asyncio.create_task(_flip_to_simulation(factory))
    try:
        await _until_waiting_on_a_row_lock(factory)
        assert not flip.done(), "the flip finished while an opening held the user row"
        held.released.set()
        result = await asyncio.wait_for(opening, WAIT_SECONDS)
        with pytest.raises(ModeChangeRefusedError) as refused:
            await asyncio.wait_for(flip, WAIT_SECONDS)
    finally:
        held.released.set()
        for task in (opening, flip):
            if not task.done():
                task.cancel()
        await asyncio.gather(opening, flip, return_exceptions=True)

    assert result.outcome is DecisionOutcome.FULL
    assert refused.value.refusal is ModeRefusal.SIMULATION_NEEDS_FLAT
    assert list(refused.value.symbols) == ["BTCUSDT"]
    assert await _reservations_of(factory, command.signal_id) == [Mode.LIVE.value]
    assert await _mode_of_user(factory, OWNER_ID) == Mode.LIVE.value


async def test_an_opening_that_starts_after_the_flip_runs_in_simulation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _set_user_mode(factory, OWNER_ID, Mode.LIVE)
    await _flip_to_simulation(factory)
    async with factory() as session:
        pre_checked = await SqlAlchemyUserMode(session, brake=False).current_mode(OWNER_ID)
    command = await _opening(factory, strategy_id, pre_checked_mode=pre_checked)

    await _allocate(factory, command)

    assert await _reservations_of(factory, command.signal_id) == [Mode.SIMULATION.value]


@pytest.mark.parametrize(
    ("user_mode", "brake", "expected"),
    [
        (Mode.LIVE, False, Mode.LIVE),
        (Mode.SIMULATION, False, Mode.SIMULATION),
        (Mode.LIVE, True, Mode.SIMULATION),
    ],
)
async def test_the_pre_check_reads_the_mode_without_waiting_for_a_row_lock(
    pg_session_factory: async_sessionmaker[AsyncSession],
    user_mode: Mode,
    brake: bool,
    expected: Mode,
) -> None:
    """The pre-checks run before the pool's advisory lock, so a row lock there would
    invert the lock order. A flip holding the row does not hold them up: they read
    the committed mode, under the brake, and the lock decides later."""
    factory = pg_session_factory
    await _set_user_mode(factory, OWNER_ID, user_mode)

    async def pre_check() -> Mode:
        async with factory() as session:
            return await SqlAlchemyUserMode(session, brake=brake).current_mode(OWNER_ID)

    async with factory() as flip:
        await flip.execute(select(UserRow.id).where(UserRow.id == OWNER_ID).with_for_update())
        task = asyncio.create_task(pre_check())
        try:
            done, _ = await asyncio.wait({task}, timeout=1.0)
            assert task in done, "the pre-check waited for the user row"
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert task.result() is expected


@pytest.mark.parametrize("mode", list(Mode))
async def test_an_allocations_mode_is_what_its_reservation_recorded(
    pg_session_factory: async_sessionmaker[AsyncSession], mode: Mode
) -> None:
    """Whatever the user's mode says now: a flip moves the next opening, never this."""
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _holding(factory, strategy_id, mode=mode, amount="10")
    other = Mode.SIMULATION if mode is Mode.LIVE else Mode.LIVE
    await _set_user_mode(factory, OWNER_ID, other)
    async with factory() as session:
        allocation_id = (await session.execute(select(ReservationRow.id))).scalar_one()

        assert await SqlAlchemyAllocationMode(session).mode_of(OWNER_ID, allocation_id) is mode


async def test_another_users_allocation_has_no_mode_to_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _holding(factory, strategy_id, mode=Mode.LIVE, amount="10")
    async with factory() as session:
        allocation_id = (await session.execute(select(ReservationRow.id))).scalar_one()

        with pytest.raises(InvariantViolation):
            await SqlAlchemyAllocationMode(session).mode_of(uuid4(), allocation_id)


async def test_reading_an_allocations_mode_waits_for_no_row_lock(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``PlaceOrder`` holds the reservation ``FOR UPDATE``, and the readers of this
    run before any lock: a row lock here would invert the lock order."""
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _holding(factory, strategy_id, mode=Mode.LIVE, amount="10")

    async def read(allocation_id: UUID) -> Mode:
        async with factory() as session:
            return await SqlAlchemyAllocationMode(session).mode_of(OWNER_ID, allocation_id)

    async with factory() as holder:
        allocation_id = (
            await holder.execute(select(ReservationRow.id).with_for_update())
        ).scalar_one()
        task = asyncio.create_task(read(allocation_id))
        try:
            done, _ = await asyncio.wait({task}, timeout=1.0)
            assert task in done, "the read waited for the reservation's row"
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert task.result() is Mode.LIVE


@pytest.mark.parametrize("mode", list(Mode))
async def test_the_snapshot_placing_an_order_carries_the_mode_recorded(
    pg_session_factory: async_sessionmaker[AsyncSession], mode: Mode
) -> None:
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _holding(factory, strategy_id, mode=mode, amount="10")
    async with factory() as session:
        reservation_id = (await session.execute(select(ReservationRow.id))).scalar_one()
        gateway = ReservationGatewayAdapter(SqlAlchemyReservationRepository(session))

        snapshot = await gateway.get_for_update(OWNER_ID, reservation_id)

    assert snapshot.mode is mode

"""``Leave`` against a queued opening, on real PostgreSQL (owner decision 4; tasks.md
N1, N5, E2.2). Both take the user's pool lock, so whichever goes first decides:

- ``Leave`` first: the subscription ends, and the opening that waited reads that and
  reserves nothing. Without the read it opened a position no close would reach.
- The opening first: its reservation is live when ``Leave`` runs, so the subscription
  goes ``LEAVING`` and the position runs until the strategy closes it.

The lock-hold harness: one actor is paused right before its commit, which is where
its locks are still held, and the test asserts the other is STILL BLOCKED after a
real wait. Every task is awaited in a ``finally``, so a red test leaves no lock held.
"""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    AllocationResult,
)
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.delivery_subscription import (
    SqlAlchemyDeliverySubscription,
)
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemyDeliveryOutcomeAdapter,
)
from strategy_manager.signals.infrastructure.skip_recorder import SignalSkipRecorder
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from strategy_manager.subscriptions.application.leave import Leave
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.adapters import (
    OpenAllocationAdapter,
    SqlAlchemyStrategyLookup,
)
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)
from tests.allocation.fakes import AlwaysEnabledPool, AnyKeyTrades, FixedUserMode
from tests.ledger.infrastructure.conftest import seed_signal
from tests.owner import allocate_command
from tests.strategies.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
MARKET = seeds.MARKET
_WAIT = 0.5
_FINISH = 10.0


class _PausedCommit:
    """Wraps a session's ``commit()``: everything the use case did is written but
    uncommitted, so every lock it took is still held, until ``resume`` is set."""

    def __init__(
        self, session: AsyncSession, reached: asyncio.Event, resume: asyncio.Event
    ) -> None:
        self._session = session
        self._reached = reached
        self._resume = resume

    async def commit(self) -> None:
        self._reached.set()
        await self._resume.wait()
        await self._session.commit()


def _leave(session: AsyncSession, *, commit: object | None = None) -> Leave:
    ledger = SqlAlchemyLedgerRepository(session)
    return Leave(
        subscriptions=SqlAlchemySubscriptionRepository(session),
        strategies=SqlAlchemyStrategyLookup(session),
        allocations=OpenAllocationAdapter(session, ledger, ReadSymbolHoldings(ledger)),
        pool_lock=PoolLockAdapter(session),
        commit=commit if commit is not None else session,  # type: ignore[arg-type]
        clock=SystemClock(),
    )


def _allocate(
    session: AsyncSession, user_id: UUID, *, commit: object | None = None
) -> AllocateCapital:
    balances = FakeBalanceSource()
    balances.set_balance(*MARKET, Decimal("1000"))
    config = {
        (user_id, MARKET): PoolConfig(
            exchange=Exchange.BYBIT,
            venue=Venue.USDT_M,
            settlement_currency=Currency.USDT,
            user_id=user_id,
            min_order_size=Decimal("1"),
        )
    }
    clock = SystemClock()
    return AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
        pool_balance=PoolBalanceAdapter(config, balances),
        lock=PgAdvisoryLockAdapter(session),
        reservations=SqlAlchemyReservationRepository(session),
        commit=commit if commit is not None else session,  # type: ignore[arg-type]
        clock=clock,
        reservation_ttl_seconds=30,
        skip_recorder=SignalSkipRecorder(SqlAlchemyDeliveryOutcomeAdapter(session, clock)),
        pool_status=AlwaysEnabledPool(),
        user_mode=FixedUserMode(),
        trade_capability=AnyKeyTrades(),
        subscription_state=SqlAlchemyDeliverySubscription(session),
    )


async def _queued_opening(factory: Factory) -> tuple[UUID, AllocateCommand]:
    """A subscriber who is not the author, and an opening delivery of theirs that
    has not reached the pool lock yet."""
    strategy_id = await seeds.strategy(factory)
    subscriber, pool_id = await seeds.user(factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(factory, subscriber, strategy_id, pool_id)
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    command = await allocate_command(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        user_id=subscriber,
    )
    return subscription_id, command


async def _reservations(factory: Factory, command: AllocateCommand) -> list[str]:
    async with factory() as session:
        result = await session.execute(
            select(ReservationRow.status).where(ReservationRow.signal_id == command.signal_id)
        )
        return list(result.scalars().all())


async def _delivery(factory: Factory, delivery_id: UUID) -> SignalDeliveryRow:
    async with factory() as session:
        row = await session.get(SignalDeliveryRow, delivery_id)
        assert row is not None
        return row


async def _settle(*tasks: asyncio.Task[object] | asyncio.Task[None]) -> None:
    """Lets every task end (bounded) and cancels what does not, so no lock outlives
    the test."""
    pending = [task for task in tasks if not task.done()]
    if pending:
        await asyncio.wait(pending, timeout=_FINISH)
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_an_opening_that_waited_for_leave_reserves_nothing(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    subscription_id, command = await _queued_opening(pg_session_factory)
    reached, resume = asyncio.Event(), asyncio.Event()
    outcome: dict[str, AllocationResult] = {}

    async def run_leave() -> None:
        async with pg_session_factory() as session:
            await _leave(session, commit=_PausedCommit(session, reached, resume)).leave(
                command.user_id, subscription_id
            )

    async def run_allocate() -> None:
        async with pg_session_factory() as session:
            outcome["value"] = await _allocate(session, command.user_id).allocate(command)

    leaving = asyncio.create_task(run_leave())
    allocating: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(reached.wait(), _FINISH)
        allocating = asyncio.create_task(run_allocate())
        await asyncio.wait({allocating}, timeout=_WAIT)
        assert not allocating.done(), "the opening did not wait for the pool lock Leave holds"
    finally:
        resume.set()
        await _settle(leaving, *([allocating] if allocating else []))

    leaving.result()
    assert allocating is not None
    allocating.result()
    assert outcome["value"].skip_reason == "SUBSCRIPTION_NOT_ACTIVE"
    assert outcome["value"].reservation_id is None
    assert await _reservations(pg_session_factory, command) == []
    subscription = await seeds.row_of(pg_session_factory, subscription_id)
    assert subscription.status == SubscriptionStatus.ENDED.value
    delivery = await _delivery(pg_session_factory, command.delivery_id)
    assert delivery.status == "REJECTED"
    assert delivery.outcome_reason == "SUBSCRIPTION_NOT_ACTIVE"
    assert delivery.outcome_detail is not None
    assert "no capital reserved" in delivery.outcome_detail


async def test_leave_that_waited_for_an_opening_leaves_the_position_running(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    subscription_id, command = await _queued_opening(pg_session_factory)
    reached, resume = asyncio.Event(), asyncio.Event()
    left: dict[str, Subscription] = {}

    async def run_allocate() -> None:
        async with pg_session_factory() as session:
            commit = _PausedCommit(session, reached, resume)
            await _allocate(session, command.user_id, commit=commit).allocate(command)

    async def run_leave() -> None:
        async with pg_session_factory() as session:
            left["value"] = await _leave(session).leave(command.user_id, subscription_id)

    allocating = asyncio.create_task(run_allocate())
    leaving: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(reached.wait(), _FINISH)
        leaving = asyncio.create_task(run_leave())
        await asyncio.wait({leaving}, timeout=_WAIT)
        assert not leaving.done(), "Leave did not wait for the pool lock the opening holds"
    finally:
        resume.set()
        await _settle(allocating, *([leaving] if leaving else []))

    allocating.result()
    assert leaving is not None
    leaving.result()
    assert left["value"].status is SubscriptionStatus.LEAVING
    assert await _reservations(pg_session_factory, command) == ["PENDING"]
    subscription = await seeds.row_of(pg_session_factory, subscription_id)
    assert subscription.status == SubscriptionStatus.LEAVING.value

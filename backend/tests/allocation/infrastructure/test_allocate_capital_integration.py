"""Integration test: TXN-A end to end against a real PostgreSQL database.
Full, partial and skip decisions each write or skip a reservation row inside
the locked transaction (spec: capital-allocation § Serialized Allocation
Decision, § Pool Availability; tasks.md 4.11).
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
)
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy

pytestmark = pytest.mark.integration

_SPOT_USDT_POOL = {
    ("spot", "USDT"): PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("10"),
    )
}


def _build_allocate_capital(session: AsyncSession, balance: Decimal) -> AllocateCapital:
    balance_source = FakeBalanceSource()
    balance_source.set_balance("spot", "USDT", balance)
    return AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
        pool_balance=PoolBalanceAdapter(_SPOT_USDT_POOL, balance_source),
        lock=PgAdvisoryLockAdapter(session),
        reservations=SqlAlchemyReservationRepository(session),
        commit=session,
        clock=SystemClock(),
        reservation_ttl_seconds=30,
    )


async def test_full_allocation_writes_a_pending_reservation_inside_txn_a(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id, fill_mode="PARTIAL")
    await seed_signal(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k1"
    )

    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session, balance=Decimal("1000"))
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.outcome is DecisionOutcome.FULL
    assert result.granted == Decimal("200")

    async with pg_session_factory() as session:
        row = (
            await session.execute(
                select(ReservationRow).where(ReservationRow.signal_id == signal_id)
            )
        ).scalar_one()
        assert row.status == "PENDING"
        assert row.amount == Decimal("200")


async def test_partial_allocation_grants_only_the_available_remainder(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    first_signal_id, second_signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id, fill_mode="PARTIAL")
    await seed_signal(
        pg_session_factory,
        signal_id=first_signal_id,
        strategy_id=strategy_id,
        idempotency_key="k1",
    )
    await seed_signal(
        pg_session_factory,
        signal_id=second_signal_id,
        strategy_id=strategy_id,
        idempotency_key="k2",
    )

    # First allocation consumes 850 of the pool's 1000, leaving 150 available.
    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session, balance=Decimal("1000"))
        first = await use_case.allocate(
            AllocateCommand(
                signal_id=first_signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("850"), currency=Currency.USDT),
            )
        )
    assert first.outcome is DecisionOutcome.FULL

    # Second, larger request must be clamped to the 150 still available.
    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session, balance=Decimal("1000"))
        second = await use_case.allocate(
            AllocateCommand(
                signal_id=second_signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("300"), currency=Currency.USDT),
            )
        )

    assert second.outcome is DecisionOutcome.PARTIAL
    assert second.granted == Decimal("150")

    async with pg_session_factory() as session:
        row = (
            await session.execute(
                select(ReservationRow).where(ReservationRow.signal_id == second_signal_id)
            )
        ).scalar_one()
        assert row.amount == Decimal("150")


async def test_skip_when_no_availability_writes_no_reservation_row(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    first_signal_id, second_signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id, fill_mode="PARTIAL")
    await seed_signal(
        pg_session_factory,
        signal_id=first_signal_id,
        strategy_id=strategy_id,
        idempotency_key="k1",
    )
    await seed_signal(
        pg_session_factory,
        signal_id=second_signal_id,
        strategy_id=strategy_id,
        idempotency_key="k2",
    )

    # Fully consume the pool.
    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session, balance=Decimal("1000"))
        first = await use_case.allocate(
            AllocateCommand(
                signal_id=first_signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("1000"), currency=Currency.USDT),
            )
        )
    assert first.outcome is DecisionOutcome.FULL

    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session, balance=Decimal("1000"))
        second = await use_case.allocate(
            AllocateCommand(
                signal_id=second_signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert second.outcome is DecisionOutcome.SKIP
    assert second.skip_reason == "NO_AVAILABILITY"
    assert second.reservation_id is None

    async with pg_session_factory() as session:
        count = (
            await session.execute(
                select(ReservationRow).where(ReservationRow.signal_id == second_signal_id)
            )
        ).scalar_one_or_none()
        assert count is None

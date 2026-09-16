"""Shared harness for the concurrency race test and its negative control
(design.md's Concurrency test design; tasks.md 4.12, 4.14). Test-only code —
not part of the production package.
"""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

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
from strategy_manager.allocation.application.ports import AdvisoryLockPort
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository

POOL_BALANCE = Decimal("1000")
REQUEST_AMOUNT = Decimal("200")
CONCURRENCY = 8

SPOT_USDT_POOL = {
    ("spot", "USDT"): PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        min_order_size=Decimal("1"),
    )
}

LockFactory = Callable[[AsyncSession], AdvisoryLockPort]


def build_allocate_capital(session: AsyncSession, lock: AdvisoryLockPort) -> AllocateCapital:
    balance_source = FakeBalanceSource()
    balance_source.set_balance("spot", "USDT", POOL_BALANCE)
    return AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
        pool_balance=PoolBalanceAdapter(SPOT_USDT_POOL, balance_source),
        lock=lock,
        reservations=SqlAlchemyReservationRepository(session),
        commit=session,
        clock=SystemClock(),
        reservation_ttl_seconds=30,
    )


async def run_concurrent_allocations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    signal_ids: list[UUID],
    lock_factory: LockFactory,
) -> list[AllocationResult]:
    """Runs ``len(signal_ids)`` allocations concurrently, each on its own
    genuinely distinct connection (a real, separate ``AsyncSession``) so every
    request truly races for the advisory lock instead of serializing on a
    shared session."""

    barrier = asyncio.Event()

    async def one(signal_id: UUID) -> AllocationResult:
        async with session_factory() as session:
            use_case = build_allocate_capital(session, lock_factory(session))
            await barrier.wait()  # align the starts
            return await use_case.allocate(
                AllocateCommand(
                    signal_id=signal_id,
                    strategy_id=strategy_id,
                    requested=Money(amount=REQUEST_AMOUNT, currency=Currency.USDT),
                )
            )

    tasks = [asyncio.create_task(one(signal_id)) for signal_id in signal_ids]
    await asyncio.sleep(0)  # let every task reach the barrier before releasing it
    barrier.set()
    return await asyncio.gather(*tasks)


async def reset_reservations(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Clears every reservation row so a multi-iteration test (the negative
    control) evaluates each iteration against a fresh pool, matching
    design.md's ``reset_pool(balance=...)`` — otherwise reservations from an
    earlier iteration would still count toward the pool balance and a
    "breach" would only reflect accumulation, not the race being tested."""

    async with session_factory() as session:
        await session.execute(text("TRUNCATE reservations RESTART IDENTITY CASCADE"))
        await session.commit()


async def sum_active_reservations(session_factory: async_sessionmaker[AsyncSession]) -> Decimal:
    async with session_factory() as session:
        result = await session.execute(
            select(ReservationRow.amount).where(
                ReservationRow.venue == "spot",
                ReservationRow.settlement_currency == "USDT",
                ReservationRow.status.in_(["PENDING", "SUBMITTED"]),
            )
        )
        return sum((amount for amount in result.scalars()), Decimal("0"))

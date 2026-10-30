"""Integration test: two strategies each at 60% of the same 1000-balance
pool — the first grants 600, the second is clamped to the remaining 400 by
``decide()``, proving the percent caps the *ask* without breaking the
concurrency invariant (design.md § "Order size never comes from the alert";
tasks.md 7.9).

The share is a subscription's since migration ``0033`` dropped the strategy's
column, so ``_SHARE`` stands for it: ``requested_from_percent()`` ->
``AllocateCapital.allocate()`` against real PostgreSQL. ``decide()`` itself is
untouched.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
)
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.domain.percent import requested_from_percent
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.allocation.fakes import AlwaysEnabledPool, FixedUserMode, RecordingSkipRecorder
from tests.allocation.infrastructure.conftest import seed_signal, seed_strategy
from tests.owner import OWNER_ID, allocate_command

pytestmark = pytest.mark.integration

_SPOT_USDT_POOL = {
    (OWNER_ID, ("pionex", "spot", "USDT")): PoolConfig(
        exchange=Exchange.PIONEX,
        venue=Venue.SPOT,
        settlement_currency=Currency.USDT,
        user_id=OWNER_ID,
        min_order_size=Decimal("10"),
    )
}
_BALANCE = Decimal("1000")
_SHARE = Decimal("60")


def _build_allocate_capital(session: AsyncSession) -> AllocateCapital:
    balance_source = FakeBalanceSource()
    balance_source.set_balance("pionex", "spot", "USDT", _BALANCE)
    return AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
        pool_balance=PoolBalanceAdapter(_SPOT_USDT_POOL, balance_source),
        lock=PgAdvisoryLockAdapter(session),
        reservations=SqlAlchemyReservationRepository(session),
        commit=session,
        clock=SystemClock(),
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
        pool_status=AlwaysEnabledPool(),
        user_mode=FixedUserMode(),
    )


async def _requested_for(session: AsyncSession, strategy_id: object) -> Money:
    """Mirrors the delivery path (tasks.md 7.8): read the strategy's policy,
    then derive ``requested`` from the subscription's share applied to the pool
    balance — never from an alert."""
    policy = await StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)).policy_for(
        strategy_id  # type: ignore[arg-type]
    )
    amount = requested_from_percent(_BALANCE, _SHARE)
    return Money(amount=amount, currency=Currency(policy.settlement_currency))


async def test_two_strategies_at_60_percent_second_is_clamped_by_decide(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_strategy_id, second_strategy_id = uuid4(), uuid4()
    first_signal_id, second_signal_id = uuid4(), uuid4()

    await seed_strategy(pg_session_factory, strategy_id=first_strategy_id)
    await seed_strategy(pg_session_factory, strategy_id=second_strategy_id)
    await seed_signal(
        pg_session_factory,
        signal_id=first_signal_id,
        strategy_id=first_strategy_id,
        idempotency_key="k1",
    )
    await seed_signal(
        pg_session_factory,
        signal_id=second_signal_id,
        strategy_id=second_strategy_id,
        idempotency_key="k2",
    )

    async with pg_session_factory() as session:
        requested = await _requested_for(session, first_strategy_id)
    assert requested.amount == Decimal("600")
    first_command = await allocate_command(
        pg_session_factory,
        signal_id=first_signal_id,
        strategy_id=first_strategy_id,
        requested=requested,
    )
    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session)
        first = await use_case.allocate(first_command)
    assert first.outcome is DecisionOutcome.FULL
    assert first.granted == Decimal("600")

    async with pg_session_factory() as session:
        requested = await _requested_for(session, second_strategy_id)
    assert requested.amount == Decimal("600")  # the ask is unaffected by the first grant
    second_command = await allocate_command(
        pg_session_factory,
        signal_id=second_signal_id,
        strategy_id=second_strategy_id,
        requested=requested,
    )
    async with pg_session_factory() as session:
        use_case = _build_allocate_capital(session)
        second = await use_case.allocate(second_command)

    # decide() clamps the grant to whatever remains: 1000 - 600 = 400.
    assert second.outcome is DecisionOutcome.PARTIAL
    assert second.granted == Decimal("400")

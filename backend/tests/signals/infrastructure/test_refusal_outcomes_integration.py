"""Decision 25, tasks 5b.4/5b.5 on real PostgreSQL: a refusal or a skip is
DURABLE in ``signals`` once its commit lands, written by the real outcome
adapter on the run's own session (design.md "Addendum: signal outcomes" § C).

The fakes-based rows live in ``tests/signals/application`` and
``tests/allocation/application``; these three pin that the added commits
actually persist (a fake commit cannot prove that).
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.pool_balance_adapter import PoolBalanceAdapter
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.accounts.infrastructure.fake_balance_source import FakeBalanceSource
from strategy_manager.accounts.infrastructure.pool_status_adapter import SqlAlchemyPoolStatus
from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
)
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.outcome_repository import (
    SqlAlchemySignalOutcomeAdapter,
)
from strategy_manager.signals.infrastructure.skip_recorder import SignalSkipRecorder
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.signals.application.test_process_signal import (
    SpyAdvisoryLock,
    SpyPlaceOrder,
    _allocate_capital,
    _process_signal_handler,
    _snapshot,
)
from tests.signals.infrastructure.conftest import seed_signal_row, seed_strategy

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


async def _row(session_factory: async_sessionmaker[AsyncSession], signal_id: object) -> SignalRow:
    async with session_factory() as session:
        return (
            await session.execute(select(SignalRow).where(SignalRow.id == signal_id))
        ).scalar_one()


async def test_a_refusal_is_durable_after_the_handler_returns(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Row 3 (``PAIR_NOT_ALLOWED``) end to end: the handler stages the outcome
    on the session and commits it on the refusal path, where no commit
    existed before."""
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="r1"
    )
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="STXUSDT.P",  # TradingView spelling; the allowlist holds market keys
        price=Decimal("2"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )

    async with pg_session_factory() as session:
        handler = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            policy=_snapshot(allowed_pairs=frozenset({"ETHUSDT"})),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),  # type: ignore[arg-type]
            commit=session,
        )
        result = await handler.handle(signal_id)

    row = await _row(pg_session_factory, signal_id)
    assert row.status == "REJECTED"
    assert row.outcome_reason == "PAIR_NOT_ALLOWED"
    assert row.outcome_detail == result.refused
    assert row.decided_at == _NOW


def _allocate_capital_on(session: AsyncSession, balance: Decimal) -> AllocateCapital:
    source = FakeBalanceSource()
    source.set_balance("bybit", "usdt-m", "USDT", balance)
    pools = {
        ("bybit", "usdt-m", "USDT"): PoolConfig(
            exchange=Exchange.BYBIT,
            venue=Venue.USDT_M,
            settlement_currency=Currency.USDT,
            min_order_size=Decimal("5"),
        )
    }
    return AllocateCapital(
        strategy_policy=StrategyPolicyAdapter(SqlAlchemyStrategyRepository(session)),
        pool_balance=PoolBalanceAdapter(pools, source),
        lock=PgAdvisoryLockAdapter(session),
        reservations=SqlAlchemyReservationRepository(session),
        commit=session,
        clock=_FixedClock(),
        reservation_ttl_seconds=30,
        skip_recorder=SignalSkipRecorder(SqlAlchemySignalOutcomeAdapter(session, _FixedClock())),
        pool_status=SqlAlchemyPoolStatus(session),
    )


async def test_the_pre_lock_disabled_skip_is_durable_through_its_added_commit(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id, enabled=False)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="s1"
    )

    async with pg_session_factory() as session:
        result = await _allocate_capital_on(session, Decimal("1000")).allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.skip_reason == "STRATEGY_DISABLED"
    row = await _row(pg_session_factory, signal_id)
    assert row.status == "REJECTED"
    assert row.outcome_reason == "STRATEGY_DISABLED"
    assert row.outcome_detail is not None and str(signal_id) in row.outcome_detail


async def test_a_decide_skip_is_durable_and_takes_the_signal_lock_after_the_pool_lock(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="s2"
    )

    async with pg_session_factory() as session:
        result = await _allocate_capital_on(session, Decimal("0")).allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.skip_reason == "NO_AVAILABILITY"
    row = await _row(pg_session_factory, signal_id)
    assert row.status == "REJECTED"
    assert row.outcome_reason == "NO_AVAILABILITY"


async def test_a_release_with_no_position_is_durable_after_the_handler_returns(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decision 27: ``NO_POSITION_TO_CLOSE`` rides the refusal commit, so it
    survives the session closing. The signal row keeps Pionex's spelling while
    the context carries TradingView's."""
    caplog.set_level("WARNING", logger="strategy_manager.signals.application.process_signal")
    strategy_id, signal_id = uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key="np1",
        symbol="STXUSDT_PERP",
    )
    context = SignalContext(
        strategy_id=strategy_id,
        symbol="STXUSDT.P",
        price=Decimal("2"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=None,
        settlement_currency="USDT",
    )

    async with pg_session_factory() as session:
        handler = _process_signal_handler(
            context=context,
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            outcomes=SqlAlchemySignalOutcomeAdapter(session, _FixedClock()),  # type: ignore[arg-type]
            commit=session,
        )
        await handler.handle(signal_id)

    row = await _row(pg_session_factory, signal_id)
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert row.status == "REJECTED"
    assert row.outcome_reason == "NO_POSITION_TO_CLOSE"
    assert row.outcome_detail == warnings[0]
    assert row.decided_at == _NOW

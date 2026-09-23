"""Integration test: ``InFlightCloseAdapter.submitted_for()`` against real
PostgreSQL (design.md § 7, freshness check (g)) -- delegates to the EXISTING
``SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol`` with
NO new SQL, mirroring ``tests/signals/infrastructure
/test_in_flight_work_integration.py``'s own testing shape for the sibling
adapter that method already serves.

**Binding testing lesson (design.md § 13)**: a symbol has three spellings.
The cross-spelling case here inserts a SUBMITTED closing attempt under one
spelling and queries under a different one, or it proves nothing.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.reconciliation.infrastructure.in_flight_close_adapter import (
    InFlightCloseAdapter,
)
from tests.reconciliation.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

POOL = ("bybit", "usdt-m", "USDT")


async def _submitted_for(
    session_factory: async_sessionmaker[AsyncSession], strategy_id, symbol: str
) -> bool:
    async with session_factory() as session:
        adapter = InFlightCloseAdapter(SqlAlchemyExecutionAttemptRepository(session))
        return await adapter.submitted_for(POOL, strategy_id, symbol)


async def test_nothing_submitted_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _submitted_for(pg_session_factory, uuid4(), "STXUSDT") is False


async def test_a_submitted_closing_attempt_is_in_flight_under_a_different_spelling(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Recorded as ``STXUSDT`` (venue bare), queried as ``STXUSDT.P``
    (TradingView) -- the same market (design.md § 13)."""
    strategy_id, signal_id, allocation_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        closes_allocation_id=allocation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )

    assert await _submitted_for(pg_session_factory, strategy_id, "STXUSDT.P") is True


async def test_a_filled_closing_attempt_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id, allocation_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        closes_allocation_id=allocation_id,
        symbol="STXUSDT",
        status="FILLED",
    )

    assert await _submitted_for(pg_session_factory, strategy_id, "STXUSDT") is False


async def test_a_submitted_opening_attempt_also_counts_as_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Mirrors ``submitted_for_strategy_symbol``'s own ``COALESCE`` over
    both origins -- an opening attempt in flight is still an in-flight
    execution racing this approval, not only a closing one."""
    strategy_id, signal_id, reservation_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )

    assert await _submitted_for(pg_session_factory, strategy_id, "STXUSDT") is True


async def test_a_submitted_attempt_for_a_different_strategy_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_a, strategy_b = uuid4(), uuid4()
    signal_id, allocation_id, attempt_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_a)
    await seed_strategy(pg_session_factory, strategy_id=strategy_b)
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_a,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_a,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        closes_allocation_id=allocation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )

    assert await _submitted_for(pg_session_factory, strategy_b, "STXUSDT") is False

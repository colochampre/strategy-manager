"""Integration test: ``InFlightWorkAdapter.in_flight()`` against real
PostgreSQL (design.md § "In flight vs orphan"; spec: capital-allocation §
Existing-Position Guard).

This is a SQL join question, not a fake one: attempts carry no
``strategy_id`` of their own, so reaching it requires a real join through
``reservations r ON r.id = COALESCE(ea.reservation_id, ea.closes_allocation_id)``.

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). The
cross-spelling case here inserts an execution attempt under one spelling and
queries ``in_flight`` under a different one, or it proves nothing.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.signals.infrastructure.in_flight_work import InFlightWorkAdapter
from tests.signals.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal_row,
    seed_strategy,
)

pytestmark = pytest.mark.integration

POOL = ("bybit", "usdt-m", "USDT")
NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


async def _in_flight(
    session_factory: async_sessionmaker[AsyncSession], strategy_id, symbol: str
) -> bool:
    async with session_factory() as session:
        adapter = InFlightWorkAdapter(
            attempts=SqlAlchemyExecutionAttemptRepository(session),
            reservations=SqlAlchemyReservationRepository(session),
        )
        return await adapter.in_flight(POOL, strategy_id, symbol, NOW)


async def test_nothing_recorded_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _in_flight(pg_session_factory, uuid4(), "STXUSDT") is False


async def test_a_submitted_opening_attempt_is_in_flight_under_a_different_spelling(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Recorded as ``STXUSDT_PERP`` (Pionex), queried as ``STXUSDT.P``
    (TradingView) -- the same market."""
    strategy_id, signal_id, reservation_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
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
        symbol="STXUSDT_PERP",
        status="SUBMITTED",
    )

    assert await _in_flight(pg_session_factory, strategy_id, "STXUSDT.P") is True


async def test_a_submitted_closing_attempt_is_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A closing attempt is tied to the allocation it unwinds
    (``closes_allocation_id``), not to a reservation the join can reach
    directly -- ``closes_allocation_id`` IS the reservation id (CLAUDE.md's
    ``allocation_id`` == the opening reservation)."""
    strategy_id, signal_id, allocation_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
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

    assert await _in_flight(pg_session_factory, strategy_id, "STXUSDT_PERP") is True


async def test_a_filled_attempt_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id, reservation_id, attempt_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
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
        status="FILLED",
    )

    assert await _in_flight(pg_session_factory, strategy_id, "STXUSDT") is False


async def test_a_submitted_attempt_for_a_different_strategy_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Per strategy, not per pool: another strategy's in-flight work on the
    same symbol must not block this one."""
    strategy_a, strategy_b = uuid4(), uuid4()
    signal_id, reservation_id, attempt_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_a)
    await seed_strategy(pg_session_factory, strategy_id=strategy_b)
    await seed_signal_row(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_a,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_a,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )

    assert await _in_flight(pg_session_factory, strategy_b, "STXUSDT") is False


async def test_a_pending_reservation_within_its_ttl_is_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """(b): reservations carry no symbol, so this branch is strategy-level --
    bounded by the reservation's own TTL."""
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
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
        status="PENDING",
        expires_at=NOW + timedelta(seconds=30),
    )

    assert await _in_flight(pg_session_factory, strategy_id, "ETHUSDT") is True


async def test_an_expired_pending_reservation_is_not_in_flight(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Its own case, named explicitly in design.md: a PENDING row whose TTL
    has already passed must not keep blocking an opening signal forever."""
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal_row(
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
        status="PENDING",
        expires_at=NOW - timedelta(seconds=1),
    )

    assert await _in_flight(pg_session_factory, strategy_id, "ETHUSDT") is False

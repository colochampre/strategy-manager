"""Integration test: ``AllocationOwnerAdapter`` resolves a reservation's
owning strategy directly against real PostgreSQL [DB] -- design.md's
component inventory, the read ``PrepareBooking`` (Unit 4b) uses to populate
a booking proposal's ``strategy_id`` column from the ``allocation_id``
``classify()`` attributed a discrepancy to.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.reconciliation.infrastructure.allocation_owner_adapter import (
    AllocationOwnerAdapter,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from tests.reconciliation.infrastructure.conftest import (
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration


async def test_resolves_the_owning_strategy(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
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

    async with pg_session_factory() as session:
        resolved = await AllocationOwnerAdapter(session).strategy_for(reservation_id)

    assert resolved == strategy_id


async def test_a_different_reservations_strategy_is_not_returned(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Proves the lookup is scoped to the exact allocation id, not the
    first/any strategy in the table."""
    strategy_a, strategy_b = uuid4(), uuid4()
    signal_a, signal_b = uuid4(), uuid4()
    reservation_a, reservation_b = uuid4(), uuid4()

    await seed_strategy(pg_session_factory, strategy_id=strategy_a)
    await seed_strategy(pg_session_factory, strategy_id=strategy_b)
    await seed_signal(
        pg_session_factory,
        signal_id=signal_a,
        strategy_id=strategy_a,
        idempotency_key=f"k-{signal_a}",
    )
    await seed_signal(
        pg_session_factory,
        signal_id=signal_b,
        strategy_id=strategy_b,
        idempotency_key=f"k-{signal_b}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_a,
        strategy_id=strategy_a,
        signal_id=signal_a,
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_b,
        strategy_id=strategy_b,
        signal_id=signal_b,
    )

    async with pg_session_factory() as session:
        resolved = await AllocationOwnerAdapter(session).strategy_for(reservation_b)

    assert resolved == strategy_b


async def test_an_unknown_allocation_raises_invariant_violation(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation):
            await AllocationOwnerAdapter(session).strategy_for(uuid4())

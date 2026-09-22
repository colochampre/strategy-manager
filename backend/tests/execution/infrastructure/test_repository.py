"""Integration tests against a real PostgreSQL database (strategy_manager_test)
for ``SqlAlchemyExecutionAttemptRepository.latest_close_for`` (design.md §
S5, the continuation's idempotent release half): the most recent closing
execution attempt for an allocation, in any status, or ``None``.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from tests.execution.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


async def _seed_allocation(session_factory: async_sessionmaker[AsyncSession]) -> object:
    """Seeds a strategy + signal + reservation and returns the reservation
    id -- the allocation that a closing attempt's ``closes_allocation_id``
    (or an opening attempt's ``reservation_id``) refers to."""

    strategy_id, signal_id, allocation_id = uuid4(), uuid4(), uuid4()
    await seed_strategy(session_factory, strategy_id=strategy_id)
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
    )
    return allocation_id


async def test_latest_close_for_returns_none_when_the_allocation_has_no_closing_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_id = await _seed_allocation(pg_session_factory)
    # Only its own OPENING attempt exists -- reservation_id, not
    # closes_allocation_id -- so nothing has closed it yet.
    await seed_execution_attempt(
        pg_session_factory, attempt_id=uuid4(), reservation_id=allocation_id
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(session).latest_close_for(
            allocation_id
        )

    assert found is None


async def test_latest_close_for_returns_the_closing_attempt_scoped_to_this_allocation_only(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    allocation_a = await _seed_allocation(pg_session_factory)
    allocation_b = await _seed_allocation(pg_session_factory)
    attempt_a = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_a,
        closes_allocation_id=allocation_a,
        status="SUBMITTED",
        created_at=T0,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=allocation_b,
        status="FILLED",
        created_at=T0 + timedelta(minutes=1),
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(session).latest_close_for(
            allocation_a
        )

    assert found is not None
    assert found.id == attempt_a
    assert found.closes_allocation_id == allocation_a
    assert found.status.value == "SUBMITTED"


@pytest.mark.parametrize("status", ["FAILED", "ABORTED_EXPIRED"])
async def test_latest_close_for_returns_a_closing_attempt_in_any_status(
    pg_session_factory: async_sessionmaker[AsyncSession], status: str
) -> None:
    """``latest_close_for`` never filters by status -- the caller (design.md
    § S5's idempotent release half) is the one that decides FAILED means
    "close again", any other status means "already closing or closed"."""

    allocation_id = await _seed_allocation(pg_session_factory)
    attempt_id = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=attempt_id,
        closes_allocation_id=allocation_id,
        status=status,
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(session).latest_close_for(
            allocation_id
        )

    assert found is not None
    assert found.id == attempt_id
    assert found.status.value == status

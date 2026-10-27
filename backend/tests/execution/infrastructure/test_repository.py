"""Integration tests against a real PostgreSQL database (strategy_manager_test)
for ``SqlAlchemyExecutionAttemptRepository.latest_close_for`` (design.md §
S5, the continuation's idempotent release half): the most recent closing
execution attempt for an allocation, in any status, or ``None``; and
``submitted_closing_allocations`` (design.md § S5, amending S2): the
allocation id(s) whose closing attempt is currently SUBMITTED for a strategy
and symbol, what the rewired Existing-Position Guard in-flight branch awaits.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.shared.domain.errors import InvariantViolation
from tests.execution.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
POOL = ("bybit", "usdt-m", "USDT")


async def _seed_allocation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID | None = None,
    user_id: UUID = OWNER_ID,
) -> UUID:
    """Seeds a strategy + signal + reservation of ``user_id`` and returns the
    reservation id -- the allocation that a closing attempt's
    ``closes_allocation_id`` (or an opening attempt's ``reservation_id``)
    refers to."""

    resolved_strategy_id = strategy_id or uuid4()
    signal_id, allocation_id = uuid4(), uuid4()
    await seed_strategy(session_factory, strategy_id=resolved_strategy_id, author_id=user_id)
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=resolved_strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=allocation_id,
        strategy_id=resolved_strategy_id,
        signal_id=signal_id,
        user_id=user_id,
    )
    return allocation_id


async def _second_user(session_factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    return other


def _attempt(*, reservation_id: UUID | None, closes_allocation_id: UUID | None) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=uuid4(),
        reservation_id=reservation_id,
        closes_allocation_id=closes_allocation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("0.004"),
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.SUBMITTED,
        origin=ExecutionOrigin.SYSTEM,
        client_order_id=f"client-{uuid4()}",
        signal_id=None,
    )


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
            OWNER_ID, allocation_id
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
            OWNER_ID, allocation_a
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
            OWNER_ID, allocation_id
        )

    assert found is not None
    assert found.id == attempt_id
    assert found.status.value == status


async def test_submitted_closing_allocations_finds_a_submitted_close_under_a_different_spelling(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Binding testing lesson: recorded as ``STXUSDT_PERP`` (Pionex), queried
    as ``STXUSDT.P`` (TradingView) -- the same market."""
    strategy_id = uuid4()
    allocation_id = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=allocation_id,
        symbol="STXUSDT_PERP",
        status="SUBMITTED",
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(
            session
        ).submitted_closing_allocations(OWNER_ID, *POOL, strategy_id, "STXUSDT.P")

    assert found == [allocation_id]


async def test_submitted_closing_allocations_ignores_a_submitted_opening_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A SUBMITTED opening attempt (``reservation_id`` set) makes ``in_flight``
    True too, but it is not a close -- there is nothing here to await."""
    strategy_id = uuid4()
    allocation_id = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        reservation_id=allocation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(
            session
        ).submitted_closing_allocations(OWNER_ID, *POOL, strategy_id, "STXUSDT")

    assert found == []


async def test_submitted_closing_allocations_ignores_a_filled_close(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    allocation_id = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=allocation_id,
        symbol="STXUSDT",
        status="FILLED",
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(
            session
        ).submitted_closing_allocations(OWNER_ID, *POOL, strategy_id, "STXUSDT")

    assert found == []


async def test_submitted_closing_allocations_ignores_a_different_strategy(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_a, strategy_b = uuid4(), uuid4()
    allocation_id = await _seed_allocation(pg_session_factory, strategy_id=strategy_a)
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=allocation_id,
        symbol="STXUSDT",
        status="SUBMITTED",
    )

    async with pg_session_factory() as session:
        found = await SqlAlchemyExecutionAttemptRepository(
            session
        ).submitted_closing_allocations(OWNER_ID, *POOL, strategy_b, "STXUSDT")

    assert found == []


# ---- multi-user ownership (design AD2, AD8; tasks.md B.3, B.5, B.9) ----------


async def _seed_second_users_allocation(
    session_factory: async_sessionmaker[AsyncSession], *, strategy_id: UUID, user_id: UUID
) -> UUID:
    """A reservation of ``user_id`` on the SAME strategy (and so the same
    market), so only the user tells it apart from the owner's. A strategy has
    one author in production; this isolates the user filter from the strategy
    filter that would otherwise separate the two rows by itself."""
    signal_id, allocation_id = uuid4(), uuid4()
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
        user_id=user_id,
    )
    return allocation_id


async def _row(
    session_factory: async_sessionmaker[AsyncSession], attempt_id: UUID
) -> ExecutionAttemptRow:
    async with session_factory() as session:
        return (
            await session.execute(
                select(ExecutionAttemptRow).where(ExecutionAttemptRow.id == attempt_id)
            )
        ).scalar_one()


async def test_insert_writes_the_attempt_as_the_given_user(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user(pg_session_factory)
    allocation_id = await _seed_allocation(pg_session_factory, user_id=other)
    attempt = _attempt(reservation_id=allocation_id, closes_allocation_id=None)

    async with pg_session_factory() as session:
        await SqlAlchemyExecutionAttemptRepository(session).insert(other, attempt)
        await session.commit()

    assert (await _row(pg_session_factory, attempt.id)).user_id == other


async def test_get_never_returns_another_users_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user(pg_session_factory)
    strategy_id = uuid4()
    own_allocation = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    foreign_allocation = await _seed_second_users_allocation(
        pg_session_factory, strategy_id=strategy_id, user_id=other
    )
    own_attempt, foreign_attempt = uuid4(), uuid4()
    await seed_execution_attempt(
        pg_session_factory, attempt_id=own_attempt, reservation_id=own_allocation
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=foreign_attempt, reservation_id=foreign_allocation
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyExecutionAttemptRepository(session)
        found = await repository.get(OWNER_ID, own_attempt)
        with pytest.raises(InvariantViolation):
            await repository.get(OWNER_ID, foreign_attempt)

    assert found.id == own_attempt


@pytest.mark.parametrize("mark", ["placed", "filled", "failed"])
async def test_a_mark_never_changes_another_users_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession], mark: str
) -> None:
    other = await _second_user(pg_session_factory)
    strategy_id = uuid4()
    own_allocation = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    foreign_allocation = await _seed_second_users_allocation(
        pg_session_factory, strategy_id=strategy_id, user_id=other
    )
    own_attempt, foreign_attempt = uuid4(), uuid4()
    await seed_execution_attempt(
        pg_session_factory, attempt_id=own_attempt, reservation_id=own_allocation
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=foreign_attempt, reservation_id=foreign_allocation
    )

    async def apply(repository: SqlAlchemyExecutionAttemptRepository, attempt_id: UUID) -> None:
        if mark == "placed":
            await repository.mark_placed(OWNER_ID, attempt_id, "EX-1")
        elif mark == "filled":
            await repository.mark_filled(OWNER_ID, attempt_id, "EX-1")
        else:
            await repository.mark_failed(OWNER_ID, attempt_id, "boom")

    async with pg_session_factory() as session:
        repository = SqlAlchemyExecutionAttemptRepository(session)
        await apply(repository, foreign_attempt)
        await apply(repository, own_attempt)
        await session.commit()

    foreign = await _row(pg_session_factory, foreign_attempt)
    assert (foreign.status, foreign.exchange_order_id, foreign.error) == ("SUBMITTED", None, None)
    own = await _row(pg_session_factory, own_attempt)
    assert (own.status, own.exchange_order_id, own.error) != ("SUBMITTED", None, None)


async def test_submitted_for_strategy_symbol_never_sees_another_users_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user(pg_session_factory)
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    foreign_allocation = await _seed_second_users_allocation(
        pg_session_factory, strategy_id=strategy_id, user_id=other
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        reservation_id=foreign_allocation,
        symbol="STXUSDT",
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyExecutionAttemptRepository(session)
        owners = await repository.submitted_for_strategy_symbol(
            OWNER_ID, *POOL, strategy_id, "STXUSDT.P"
        )
        others = await repository.submitted_for_strategy_symbol(
            other, *POOL, strategy_id, "STXUSDT.P"
        )

    assert (owners, others) == (False, True)


async def test_submitted_closing_allocations_never_sees_another_users_close(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user(pg_session_factory)
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    foreign_allocation = await _seed_second_users_allocation(
        pg_session_factory, strategy_id=strategy_id, user_id=other
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=uuid4(),
        closes_allocation_id=foreign_allocation,
        symbol="STXUSDT",
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyExecutionAttemptRepository(session)
        owners = await repository.submitted_closing_allocations(
            OWNER_ID, *POOL, strategy_id, "STXUSDT"
        )
        others = await repository.submitted_closing_allocations(
            other, *POOL, strategy_id, "STXUSDT"
        )

    assert (owners, others) == ([], [foreign_allocation])


async def test_submitted_for_pool_never_lists_another_users_attempt(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    other = await _second_user(pg_session_factory)
    strategy_id = uuid4()
    own_allocation = await _seed_allocation(pg_session_factory, strategy_id=strategy_id)
    foreign_allocation = await _seed_second_users_allocation(
        pg_session_factory, strategy_id=strategy_id, user_id=other
    )
    own_attempt, foreign_attempt = uuid4(), uuid4()
    await seed_execution_attempt(
        pg_session_factory, attempt_id=own_attempt, reservation_id=own_allocation
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=foreign_attempt, reservation_id=foreign_allocation
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyExecutionAttemptRepository(session)
        owners = await repository.submitted_for_pool(OWNER_ID, *POOL)
        others = await repository.submitted_for_pool(other, *POOL)

    assert (owners, others) == ([own_attempt], [foreign_attempt])


async def test_latest_close_for_never_returns_another_users_close(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The same allocation id carries a newer close of another user's: the
    owner's read still answers with the owner's own, and with nothing at all
    when the owner has none."""
    other = await _second_user(pg_session_factory)
    allocation_id = await _seed_allocation(pg_session_factory)
    lonely_allocation = await _seed_allocation(pg_session_factory)
    own_close, foreign_close, lonely_foreign = uuid4(), uuid4(), uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=own_close,
        closes_allocation_id=allocation_id,
        status="FILLED",
        created_at=T0,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=foreign_close,
        closes_allocation_id=allocation_id,
        status="SUBMITTED",
        created_at=T0 + timedelta(minutes=1),
        user_id=other,
    )
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=lonely_foreign,
        closes_allocation_id=lonely_allocation,
        created_at=T0,
        user_id=other,
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyExecutionAttemptRepository(session)
        owners = await repository.latest_close_for(OWNER_ID, allocation_id)
        others = await repository.latest_close_for(other, allocation_id)
        nothing = await repository.latest_close_for(OWNER_ID, lonely_allocation)

    assert owners is not None and owners.id == own_close
    assert others is not None and others.id == foreign_close
    assert nothing is None

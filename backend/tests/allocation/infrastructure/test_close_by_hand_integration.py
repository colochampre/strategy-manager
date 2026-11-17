"""A user's close from the panel, end to end on a real PostgreSQL database
(subscriber-safety SS.9, scenario "A subscriber closes a position").

A subscriber holding 76 DOGE on a strategy that is still running confirms "Close now": the
worker's ``CloseByHand`` sends one reduce-only market close of 76 for that allocation, through
the production ``ClosePosition`` and a fake exchange, with the cause ``MANUAL`` and no signal.
A second run, with that close still SUBMITTED, sends none, and another user's allocation is
never touched.

The ledger holds the alert's spelling (``DOGEUSDT.P``) and the venue's bare one is what a fill
would say; the close is built under the spelling the position opened with.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.close_by_hand import CloseByHand
from strategy_manager.execution.application.close_position import ClosePosition
from strategy_manager.execution.application.close_stopped_positions import PositionCloserPort
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.fake_exchange import FakeExchangeAdapter
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
    SqlAlchemyProtectiveStopRepository,
)
from strategy_manager.execution.infrastructure.stopped_positions_reader import (
    SqlAlchemyStoppedPositionsReader,
)
from strategy_manager.ledger.application.read_held_base import ReadHeldBase
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.allocation.fakes import RecordedModes
from tests.execution.fakes import OneRegistry, RecordingOrderOutcomes
from tests.execution.infrastructure.test_stopped_positions_reader import (
    _allocation,
    _strategy,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


def _by_hand(session: AsyncSession) -> CloseByHand:
    registry = VenueExchangeRegistry(
        [FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("0.15"), fee_rate=Decimal("0"))]
    )
    attempts = SqlAlchemyExecutionAttemptRepository(session)

    @asynccontextmanager
    async def closer_for(owner: UUID) -> AsyncIterator[PositionCloserPort]:
        yield ClosePosition(
            exchanges=OneRegistry(registry),
            allocation_modes=RecordedModes(),
            attempts=attempts,
            held=ReadHeldBase(SqlAlchemyLedgerRepository(session)),
            queue=PostgresJobQueue(session),
            clock=SystemClock(),
            commit=session,
            settle_delay_seconds=0.0,
            outcomes=RecordingOrderOutcomes(),
            stops=SqlAlchemyProtectiveStopRepository(session),
        )

    return CloseByHand(
        positions=SqlAlchemyStoppedPositionsReader(session),
        closing_attempts=attempts,
        pool_lock=PoolLockAdapter(session),
        closer_for=closer_for,
        unit_of_work=session,
    )


async def _closing_attempts(factory: Factory, allocation_id: UUID) -> list[ExecutionAttemptRow]:
    async with factory() as session:
        result = await session.execute(
            select(ExecutionAttemptRow).where(
                ExecutionAttemptRow.closes_allocation_id == allocation_id
            )
        )
        return list(result.scalars().all())


async def test_a_subscribers_position_is_closed_once_and_not_again(
    pg_session_factory: Factory,
) -> None:
    running = await _strategy(pg_session_factory, enabled=True)
    held = await _allocation(
        pg_session_factory, OWNER_ID, running, [("BUY", "DOGEUSDT.P", "76", "0.1", "USDT")]
    )
    untouched = await _allocation(
        pg_session_factory, OWNER_ID, running, [("BUY", "DOGEUSDT.P", "50", "0.1", "USDT")]
    )

    async with pg_session_factory() as session:
        first = await _by_hand(session).close(OWNER_ID, held)
    async with pg_session_factory() as session:
        second = await _by_hand(session).close(OWNER_ID, held)

    assert (first, second) == (True, False)
    [close] = await _closing_attempts(pg_session_factory, held)
    assert close.status == "SUBMITTED"
    assert close.side == "SELL"
    assert close.quantity == Decimal("76")
    assert close.cause == "MANUAL"
    assert close.signal_id is None
    assert close.user_id == OWNER_ID
    assert await _closing_attempts(pg_session_factory, untouched) == []


async def test_another_users_allocation_sends_nothing(pg_session_factory: Factory) -> None:
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    running = await _strategy(pg_session_factory, enabled=True)
    theirs = await _allocation(
        pg_session_factory, other, running, [("BUY", "DOGEUSDT.P", "76", "0.1", "USDT")]
    )

    async with pg_session_factory() as session:
        sent = await _by_hand(session).close(OWNER_ID, theirs)
    async with pg_session_factory() as session:
        unknown = await _by_hand(session).close(OWNER_ID, uuid4())

    assert (sent, unknown) == (False, False)
    assert await _closing_attempts(pg_session_factory, theirs) == []

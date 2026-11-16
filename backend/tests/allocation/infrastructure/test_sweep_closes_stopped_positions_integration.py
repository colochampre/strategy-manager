"""The reservation sweep's safety close, end to end on a real PostgreSQL database
(subscriber-safety SS.8b, scenarios "A disabled strategy with a position" and "The close is
not repeated").

A disabled strategy, a subscriber still holding 0.5 SOL on it: one sweep sends a reduce-only
market close of 0.5 for that allocation, through the production ``ClosePosition`` and a fake
exchange, with the cause ``SAFETY_CLOSE`` and no signal. The next sweep sends none, because
that close is still SUBMITTED.

The ledger holds the alert's spelling (``SOLUSDT.P``) and the fake exchange the venue's own is
asked for the close under the spelling the position opened with.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.close_position import ClosePosition
from strategy_manager.execution.application.close_stopped_positions import (
    CloseStoppedPositions,
    PositionCloserPort,
)
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
from tests.owner import OWNER_ID

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


def _sweep(session: AsyncSession) -> CloseStoppedPositions:
    registry = VenueExchangeRegistry(
        [FakeExchangeAdapter(exchange="bybit", fill_price=Decimal("150"), fee_rate=Decimal("0"))]
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

    return CloseStoppedPositions(
        stopped=SqlAlchemyStoppedPositionsReader(session),
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


async def test_a_disabled_strategys_position_is_closed_once_and_not_again(
    pg_session_factory: Factory,
) -> None:
    disabled = await _strategy(pg_session_factory, enabled=False)
    held = await _allocation(
        pg_session_factory,
        OWNER_ID,
        disabled,
        [("BUY", "SOLUSDT.P", "0.5", "0.04125", "USDT")],
    )
    running = await _strategy(pg_session_factory, enabled=True)
    untouched = await _allocation(
        pg_session_factory, OWNER_ID, running, [("BUY", "SOLUSDT.P", "0.5", "0.04125", "USDT")]
    )

    async with pg_session_factory() as session:
        first = await _sweep(session).sweep()
    async with pg_session_factory() as session:
        second = await _sweep(session).sweep()

    assert (first, second) == (1, 0)
    [close] = await _closing_attempts(pg_session_factory, held)
    assert close.status == "SUBMITTED"
    assert close.side == "SELL"
    assert close.quantity == Decimal("0.5")
    assert close.cause == "SAFETY_CLOSE"
    assert close.signal_id is None
    assert close.user_id == OWNER_ID
    assert await _closing_attempts(pg_session_factory, untouched) == []

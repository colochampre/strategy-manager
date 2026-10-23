"""Whose key a worker job trades and reads with (multi-user design AD8, tasks.md
B.5 and B.7).

A signal is executed in its strategy author's pool with the author's key, so a
job that works on a signal, or on the execution attempt a signal produced,
belongs to that author. These reads resolve the owner before the job builds a
single client, so no adapter is ever signed with another user's key.

``execution_attempts`` carries ``user_id`` in the database since migration
0030, but its ORM row does not map it yet (a later unit of PR B), so an attempt
is resolved through the reservation it opened or closes, whose strategy names
the author. Both links point at ``reservations``: an OPEN through
``reservation_id``, a CLOSE through ``closes_allocation_id``, the OPENING
allocation's reservation. Either way the strategy is the same one.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.strategies.infrastructure.models import StrategyRow


async def signal_owner(session: AsyncSession, signal_id: UUID) -> UUID | None:
    """The author of the strategy ``signal_id`` belongs to; ``None`` when the
    signal or its strategy is gone, and the job then fails on that itself."""
    owner = (
        await session.execute(
            select(StrategyRow.author_id)
            .join(SignalRow, SignalRow.strategy_id == StrategyRow.id)
            .where(SignalRow.id == signal_id)
        )
    ).scalar_one_or_none()
    return owner


async def attempt_owner(session: AsyncSession, attempt_id: UUID) -> UUID | None:
    """The author of the strategy behind execution attempt ``attempt_id``;
    ``None`` when the attempt, its reservation or its strategy is gone."""
    reservation_id = func.coalesce(
        ExecutionAttemptRow.reservation_id, ExecutionAttemptRow.closes_allocation_id
    )
    owner = (
        await session.execute(
            select(StrategyRow.author_id)
            .select_from(ExecutionAttemptRow)
            .join(ReservationRow, ReservationRow.id == reservation_id)
            .join(StrategyRow, StrategyRow.id == ReservationRow.strategy_id)
            .where(ExecutionAttemptRow.id == attempt_id)
        )
    ).scalar_one_or_none()
    return owner

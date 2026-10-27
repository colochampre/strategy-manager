"""Whose key a worker job trades and reads with (multi-user design AD8, tasks.md
B.5 and B.7).

A signal is executed in its strategy author's pool with the author's key, so a
job that works on a signal, or on the execution attempt a signal produced,
belongs to that author. These reads resolve the owner before the job builds a
single client, so no adapter is ever signed with another user's key.

An execution attempt carries its own ``user_id`` (migration 0030): the user of
the reservation it spends (an OPEN) or unwinds (a CLOSE), which is the strategy
author on the signal path. So it is read straight off the attempt.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """The user execution attempt ``attempt_id`` belongs to; ``None`` when the
    attempt is gone. An attempt is written as the user of the reservation it
    spends or unwinds, which is its strategy's author on the signal path."""
    owner = (
        await session.execute(
            select(ExecutionAttemptRow.user_id).where(ExecutionAttemptRow.id == attempt_id)
        )
    ).scalar_one_or_none()
    return owner

"""Whose key a worker job trades and reads with (multi-user design AD8, tasks.md
B.5 and B.7).

A delivery is executed in its SUBSCRIBER's pool with the subscriber's key, so a
job that works on a delivery, or on the execution attempt it produced, belongs to
that user. So does the reverse continuation (``signal.open_after_close``), which
since C.8 is keyed by the delivery too. These reads resolve the owner before the job
builds a single client, so no adapter is ever signed with another user's key.

An execution attempt carries its own ``user_id`` (migration 0030): the user of
the reservation it spends (an OPEN) or unwinds (a CLOSE), which is the delivery's
user on the signal path. So it is read straight off the attempt.
"""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
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


async def delivery_owner(session: AsyncSession, delivery_id: UUID) -> UUID | None:
    """The subscriber a delivery is for: its own ``user_id``, never the author of
    the strategy (multi-user design AD5; tasks.md C.6). ``None`` when the delivery
    is gone, and the job then fails on that itself."""
    owner = (
        await session.execute(
            select(SignalDeliveryRow.user_id).where(SignalDeliveryRow.id == delivery_id)
        )
    ).scalar_one_or_none()
    return owner


class UnresolvableContinuation(Exception):
    """A ``signal.open_after_close`` payload that names no single delivery."""


def _payload_uuid(payload: Mapping[str, object], key: str) -> UUID | None:
    raw = payload.get(key)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        raise UnresolvableContinuation(f"the payload carries a bad {key}: {raw!r}") from None


async def continuation_delivery_id(session: AsyncSession, payload: Mapping[str, object]) -> UUID:
    """The delivery a ``signal.open_after_close`` payload works (tasks.md C.8).

    A payload names its ``delivery_id``. A job queued before C.8 names only the
    ``signal_id`` it was keyed by, and then resolves to the signal's ONLY delivery:
    that is the author's on every signal there was when it was queued, since
    production had one subscriber per strategy. A signal with several deliveries (or
    none) cannot be resolved without choosing a subscriber to open a position for, so
    it raises ``UnresolvableContinuation`` and the caller refuses the job loudly."""
    delivery_id = _payload_uuid(payload, "delivery_id")
    if delivery_id is not None:
        return delivery_id
    signal_id = _payload_uuid(payload, "signal_id")
    if signal_id is None:
        raise UnresolvableContinuation("the payload names neither a delivery_id nor a signal_id")
    found = (
        (
            await session.execute(
                select(SignalDeliveryRow.id).where(SignalDeliveryRow.signal_id == signal_id)
            )
        )
        .scalars()
        .all()
    )
    if len(found) == 1:
        return found[0]
    raise UnresolvableContinuation(
        f"signal {signal_id} has no delivery"
        if not found
        else f"signal {signal_id} has {len(found)} deliveries, so a continuation queued "
        "for the signal alone cannot tell which subscriber it opens for"
    )


async def attempt_owner(session: AsyncSession, attempt_id: UUID) -> UUID | None:
    """The user execution attempt ``attempt_id`` belongs to; ``None`` when the
    attempt is gone. An attempt is written as the user of the delivery that placed
    it (``PlaceCommand.user_id`` / ``CloseCommand.user_id`` are the delivery's), which
    may be a subscriber who is not the strategy's author. It is read off the attempt
    and not through ``delivery_id``: an orphan close carries no delivery at all and
    still has an owner."""
    owner = (
        await session.execute(
            select(ExecutionAttemptRow.user_id).where(ExecutionAttemptRow.id == attempt_id)
        )
    ).scalar_one_or_none()
    return owner

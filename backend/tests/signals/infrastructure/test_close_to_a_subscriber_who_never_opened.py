"""A close delivered to a subscriber whose awaited opening never held (B1 recheck).

Since the B1 fix, a close is fanned out to a subscription that has a pending
(ACCEPTED or PROCESSING) delivery of an EARLIER opening on the symbol. When that
opening is then refused, the close delivery runs for a subscriber who holds nothing.
``latest_before`` returns the subscription's latest reservation on the symbol in ANY
status, so after an earlier, completed round trip it returns that old allocation,
whose close already FILLED: ``_handle_releases`` reports success without recording an
outcome. The delivery stays ``ACCEPTED`` for ever, and nothing is logged. Before PR C
the same close was refused ``NO_POSITION_TO_CLOSE`` with a WARNING.

The second case is what 0032's backfill leaves in production: a delivery copied from
a signal that stayed ``ACCEPTED`` and has no job, so it never runs. It makes the
subscription a "holder" of every later close on that symbol, backlog or not.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from strategy_manager.signals.infrastructure.models import SignalDeliveryRow
from tests.signals.infrastructure import test_delivery_flow_integration as flow
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.signals.infrastructure.test_close_queued_before_open_delivery import (
    _enqueue_signal_job,
    _jobs_left,
    _work_the_backlog,
)

pytestmark = pytest.mark.integration


async def _delivery_of(world: flow.World, signal_id: UUID, user: UUID) -> SignalDeliveryRow | None:
    async with world.factory() as session:
        return (
            await session.execute(
                select(SignalDeliveryRow).where(
                    SignalDeliveryRow.signal_id == signal_id, SignalDeliveryRow.user_id == user
                )
            )
        ).scalar_one_or_none()


async def _one_signal_through_the_worker(
    world: flow.World, position_size: str, minutes: int
) -> UUID:
    signal_id = await flow._signal(world, position_size=position_size, minutes=minutes)
    await _enqueue_signal_job(world, signal_id)
    await _work_the_backlog(world)
    return signal_id


async def _a_completed_round_trip(world: flow.World) -> None:
    await _one_signal_through_the_worker(world, "1", 1)
    await _one_signal_through_the_worker(world, "0", 2)
    assert await flow._held(world, world.other) == 0
    assert await _jobs_left(world) == []


async def test_a_backlogged_close_after_a_refused_opening_ends_with_an_outcome(
    pg_session_factory: flow.Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="strategy_manager.signals.application.process_signal")
    world = await flow._world(pg_session_factory)
    await _a_completed_round_trip(world)
    orders_before = len(world.venues[world.other].orders)
    # The other subscriber's pool is now empty, so their next opening is refused.
    world.totals[world.other] = Decimal("0")
    opening = await flow._signal(world, position_size="1", minutes=3)
    closing = await flow._signal(world, position_size="0", minutes=4)
    await _enqueue_signal_job(world, opening)
    await _enqueue_signal_job(world, closing)

    await _work_the_backlog(world)

    assert len(world.venues[world.other].orders) == orders_before
    delivery = await _delivery_of(world, closing, world.other)
    # The opening's job was still queued when the close fanned out, so the close was
    # delivered; the reservation it finds is the earlier round trip's, closed by
    # another delivery. There is nothing to close, and it says so.
    assert delivery is not None
    assert (delivery.status, delivery.outcome_reason) == ("REJECTED", "NO_POSITION_TO_CLOSE")
    assert any(
        record.levelno == logging.WARNING
        and str(closing) in record.getMessage()
        and "already closed by another delivery" in record.getMessage()
        for record in caplog.records
    )


async def test_a_backfilled_opening_that_never_ran_does_not_make_a_holder_of_every_close(
    pg_session_factory: flow.Factory,  # noqa: F811
) -> None:
    world = await flow._world(pg_session_factory)
    # What 0032 copies from a signal that stayed ACCEPTED: a delivery with no job. A
    # later close of that same old position follows it, so the chain classifies.
    stale = uuid4()
    for signal_id, size, at in (
        (stale, "1", world.t0 - timedelta(minutes=2)),
        (uuid4(), "0", world.t0 - timedelta(minutes=1)),
    ):
        await flow.seed_signal_row(
            world.factory,
            signal_id=signal_id,
            strategy_id=world.strategy_id,
            idempotency_key=f"key-{signal_id}",
            symbol=flow.ALERT,
            position_size=Decimal(size),
            received_at=at,
        )
    async with world.factory() as session:
        session.add(
            SignalDeliveryRow(
                id=uuid4(),
                signal_id=stale,
                subscription_id=world.other_subscription,
                user_id=world.other,
                status="ACCEPTED",
            )
        )
        await session.commit()
    await _a_completed_round_trip(world)
    world.totals[world.other] = Decimal("0")
    await _one_signal_through_the_worker(world, "1", 3)

    closing = await _one_signal_through_the_worker(world, "0", 4)

    delivery = await _delivery_of(world, closing, world.other)
    # The backfilled delivery has no job, so it never runs and holds nothing: the
    # close never reaches this subscriber.
    assert delivery is None, (delivery.status, delivery.outcome_reason)

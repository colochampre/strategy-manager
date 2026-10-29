"""Two reverses ingested before the worker reaches them (PR C verifier, B1b).

The first reverse closes the long allocation. The second finds that allocation as
its prior, with a close that belongs to the FIRST reverse's delivery. That close is
not this delivery's, but a reverse still waits for it and opens the new side, as it
always did: the first reverse's continuation is superseded by the second, so
refusing here would leave every subscriber flat while the strategy is long.
"""

from uuid import UUID

import pytest

from tests.signals.infrastructure import test_close_queued_before_open_delivery as q
from tests.signals.infrastructure import test_delivery_flow_integration as flow
from tests.signals.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401

pytestmark = pytest.mark.integration


async def test_two_backlogged_reverses_end_on_the_strategys_side(
    pg_session_factory: flow.Factory,  # noqa: F811
) -> None:
    """Long, then two reverses (short, long) ingested before the worker reaches them.
    The first reverse's continuation is superseded by the second; the second must
    still close and open, so every subscriber ends long, as the strategy is."""
    world = await flow._world(pg_session_factory)
    opening = await flow._signal(world, position_size="1", minutes=1)
    await q._enqueue_signal_job(world, opening)
    await q._work_the_backlog(world)
    assert await flow._held(world, world.author) > 0
    assert await flow._held(world, world.other) > 0

    # Fresh signals (t0 is 30 minutes back): a continuation abandons past 600 s.
    first = await flow._signal(world, position_size="-1", minutes=28)
    second = await flow._signal(world, position_size="1", minutes=29)
    await q._enqueue_signal_job(world, first)
    await q._enqueue_signal_job(world, second)
    done: set[UUID] = set()
    for _ in range(4):
        await q._drain(world)
        await flow._settle_all(world)
        await flow._continue(world, done)
        await flow._settle_all(world)
        await q._retries_are_due(world)

    assert await flow._held(world, world.author) > 0
    assert await flow._held(world, world.other) > 0

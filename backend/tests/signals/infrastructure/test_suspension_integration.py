"""A suspended account, or a suspended author, opens nothing; closes keep running
(public-site LS9, PS.13 S3 and S4), end to end on real PostgreSQL.

Built the way the worker builds it (``main._build_fan_out_signal`` and
``main._build_process_delivery``), reusing the two-subscriber world of the delivery-flow
tests. ``AuthorStandingPolicy`` is what fills ``StrategyPolicySnapshot.author_suspended``,
and that field defaults to False: a composition root that forgot to wrap its policy port
would open for a suspended author's subscribers without a word. The author tests here go
through ``_build_process_delivery``, so they are what pins the wiring.

A symbol wears a different spelling on each side: the alert says ``STXUSDT.P``, the venue
and the ledger say ``STXUSDT``.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select, text

from strategy_manager.execution.infrastructure.stopped_positions_reader import (
    SqlAlchemyStoppedPositionsReader,
)
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.signals.infrastructure.test_delivery_flow_integration import (
    Factory,
    World,
    _attempts,
    _continue,
    _fan_out,
    _held,
    _outcome,
    _queued,
    _reservations,
    _run,
    _settle_all,
    _signal,
    _work,
    _world,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _nobody_stays_suspended(
    pg_session_factory: Factory,  # noqa: F811
) -> AsyncIterator[None]:
    """``users`` outlives a fixture's truncate, so a suspension left by one test would
    refuse the openings of the next (the owner is every strategy's author)."""
    await _lift_everyone(pg_session_factory)
    yield
    await _lift_everyone(pg_session_factory)


async def _lift_everyone(factory: Factory) -> None:
    async with factory() as session:
        await session.execute(text("UPDATE users SET suspended_at = NULL"))
        await session.commit()


async def _suspend(world: World, user: UUID) -> None:
    async with world.factory() as session:
        await session.execute(
            text("UPDATE users SET suspended_at = now() WHERE id = :id"), {"id": user}
        )
        await session.commit()


async def _events(world: World, user: UUID) -> list[tuple[str, str, dict[str, str]]]:
    async with world.factory() as session:
        rows = (
            (await session.execute(select(SafetyEventRow).where(SafetyEventRow.user_id == user)))
            .scalars()
            .all()
        )
    return [(row.kind, row.symbol, dict(row.detail)) for row in rows]


async def _reverse(world: World) -> tuple[UUID, dict[UUID, tuple[UUID, str]]]:
    """The strategy holds its long for both subscribers; one flips it to short. Works every
    delivery, then every continuation, then settles."""
    reverse = await _signal(world, position_size="-1", minutes=29)
    await _fan_out(world, reverse)
    queued = await _queued(world, reverse)
    for user, (delivery_id, halves) in queued.items():
        await _work(world, user, delivery_id, halves)
    await _settle_all(world)
    await _continue(world, set())
    await _settle_all(world)
    return reverse, queued


# --- S3: the account ----------------------------------------------------------------


async def test_a_suspended_subscriber_opens_nothing_and_the_other_subscriber_still_does(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _suspend(world, world.other)
    signal_id = await _signal(world, position_size="1", minutes=1)

    queued = await _run(world, signal_id)

    assert set(await _reservations(world, signal_id)) == {world.author}
    assert await _attempts(world, world.other) == []
    assert world.venues[world.other].orders == []
    assert await _held(world, world.other) == Decimal("0")
    assert await _outcome(world, queued[world.other][0]) == ("REJECTED", "ACCOUNT_SUSPENDED")
    assert await _outcome(world, queued[world.author][0]) == ("PROCESSED", None)
    assert await _events(world, world.other) == [
        ("OPENING_REFUSED_ACCOUNT_SUSPENDED", "STXUSDT", {})
    ]
    assert await _events(world, world.author) == []


async def test_a_close_for_a_suspended_subscriber_still_executes(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    assert await _held(world, world.other) == Decimal("100")
    await _suspend(world, world.other)

    queued = await _run(world, await _signal(world, position_size="0", minutes=2))

    assert await _held(world, world.other) == Decimal("0")
    assert await _outcome(world, queued[world.other][0]) == ("PROCESSED", None)
    assert await _events(world, world.other) == []


async def test_a_reverse_for_a_suspended_subscriber_closes_and_refuses_the_new_side(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    await _suspend(world, world.other)

    reverse, _ = await _reverse(world)

    assert await _held(world, world.other) == Decimal("0")
    assert await _held(world, world.author) == Decimal("-500")
    assert set(await _reservations(world, reverse)) == {world.author}
    assert [kind for kind, _, _ in await _events(world, world.other)] == [
        "OPENING_REFUSED_ACCOUNT_SUSPENDED"
    ]


# --- S4: the author -------------------------------------------------------------------


async def test_a_suspended_authors_strategy_opens_for_nobody(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _suspend(world, world.author)
    signal_id = await _signal(world, position_size="1", minutes=1)

    queued = await _run(world, signal_id)

    assert await _reservations(world, signal_id) == {}
    for user in (world.author, world.other):
        assert await _attempts(world, user) == []
        assert world.venues[user].orders == []
    # The subscriber is refused for the AUTHOR; the author, for their own account.
    assert await _outcome(world, queued[world.other][0]) == ("REJECTED", "AUTHOR_SUSPENDED")
    assert await _outcome(world, queued[world.author][0]) == ("REJECTED", "ACCOUNT_SUSPENDED")
    assert await _events(world, world.other) == [
        ("OPENING_REFUSED_AUTHOR_SUSPENDED", "STXUSDT", {})
    ]


async def test_a_close_on_a_suspended_authors_strategy_executes_for_its_subscribers(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    await _suspend(world, world.author)

    queued = await _run(world, await _signal(world, position_size="0", minutes=2))

    assert await _held(world, world.other) == Decimal("0")
    assert await _held(world, world.author) == Decimal("0")
    assert await _outcome(world, queued[world.other][0]) == ("PROCESSED", None)


async def test_a_reverse_on_a_suspended_authors_strategy_closes_and_refuses_the_new_side(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    await _suspend(world, world.author)

    reverse, _ = await _reverse(world)

    assert await _held(world, world.other) == Decimal("0")
    assert await _reservations(world, reverse) == {}
    assert [kind for kind, _, _ in await _events(world, world.other)] == [
        "OPENING_REFUSED_AUTHOR_SUSPENDED"
    ]


# --- the sweep ------------------------------------------------------------------------


async def test_the_sweep_does_not_close_positions_on_a_suspended_authors_strategy(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Suspension is not ``enabled = false``: the sweep would sell the subscribers'
    positions at market. The control is the same strategy once it IS disabled."""
    world = await _world(pg_session_factory)
    await _run(world, await _signal(world, position_size="1", minutes=1))
    await _suspend(world, world.author)

    async with world.factory() as session:
        assert await SqlAlchemyStoppedPositionsReader(session).stopped_positions() == []

    async with world.factory() as session:
        await session.execute(
            text("UPDATE strategies SET enabled = false WHERE id = :id"),
            {"id": world.strategy_id},
        )
        await session.commit()
    async with world.factory() as session:
        stopped = await SqlAlchemyStoppedPositionsReader(session).stopped_positions()
    assert world.other in {position.user_id for position in stopped}

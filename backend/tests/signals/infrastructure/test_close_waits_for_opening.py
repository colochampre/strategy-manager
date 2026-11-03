"""A close whose opening is still in flight waits for it (multi-user tasks.md, G.6).

An opening can stay ``SUBMITTED`` for minutes: its fills land when the settle job finds
them, on the job's backoff, and the sweeper expires its reservation at the TTL all the
same. Two windows follow. While the reservation lives the close is delivered, finds no
fill and used to retry on the failure backoff, up to 240 s after the fill. Once the
reservation expires the close reached nobody, and the later fill was a position the
strategy had already left.

Real adapters from fan-out to settlement, on real PostgreSQL. Only the venue is
replaced, and nothing settles until a test says so. The alert says ``STXUSDT.P``, the
attempt and the ledger say whatever the venue says.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.main import _build_settle_execution
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.application.fan_out_signal import DeliveryHalves
from strategy_manager.signals.infrastructure.delivery_adapters import SqlAlchemyOpeningStates
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow
from tests.owner import OWNER_ID, ensure_pool
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.signals.infrastructure.test_delivery_flow_integration import (
    ETH_ALERT,
    MARKET,
    Factory,
    World,
    _continue,
    _fan_out,
    _held,
    _outcome,
    _queued,
    _reservations,
    _settle_all,
    _signal,
    _work,
    _world,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

CLOSE = DeliveryHalves.CLOSE.value
BOTH = DeliveryHalves.BOTH.value


async def _opening_in_flight(world: World, *, symbol: str | None = None) -> UUID:
    """An opening worked for every subscriber, whose orders no settle has read."""
    signal = (
        await _signal(world, position_size="1", minutes=1)
        if symbol is None
        else await _signal(world, position_size="1", minutes=1, symbol=symbol)
    )
    await _fan_out(world, signal)
    for user, (delivery_id, halves) in (await _queued(world, signal)).items():
        await _work(world, user, delivery_id, halves)
    # What the worker's ack does. A delivery job left live reads as an opening yet to
    # run (``_awaits_opening``), which would hide the very window under test.
    async with world.factory() as session:
        await session.execute(
            update(JobRow).where(JobRow.kind == "delivery.process").values(status="DONE")
        )
        await session.commit()
    return signal


async def _sweep_reservations(world: World) -> None:
    """The real sweeper, past every TTL: a reservation of an order in flight expires
    while the order may still fill."""
    async with world.factory() as session:
        await SqlAlchemyReservationRepository(session).expire_due(
            datetime.now(UTC) + timedelta(hours=1), 100
        )
        await session.commit()


async def _polls(world: World, delivery_id: UUID) -> list[dict[str, object]]:
    """The payload of every poll this delivery seeded, in order."""
    async with world.factory() as session:
        jobs = (
            (
                await session.execute(
                    select(JobRow)
                    .where(JobRow.kind == "delivery.process")
                    .order_by(JobRow.created_at, JobRow.id)
                )
            )
            .scalars()
            .all()
        )
    return [
        dict(job.payload)
        for job in jobs
        if job.payload.get("delivery_id") == str(delivery_id) and "poll" in job.payload
    ]


async def _run_after(world: World, delivery_id: UUID, poll: int) -> datetime:
    async with world.factory() as session:
        return (
            await session.execute(
                select(JobRow.run_after).where(
                    JobRow.dedupe_key == f"delivery:{delivery_id}:after-opening:{poll}"
                )
            )
        ).scalar_one()


async def _attempts_aged(world: World, seconds: float) -> None:
    async with world.factory() as session:
        await session.execute(
            update(ExecutionAttemptRow).values(
                created_at=datetime.now(UTC) - timedelta(seconds=seconds)
            )
        )
        await session.commit()


async def _detail(world: World, delivery_id: UUID) -> str:
    async with world.factory() as session:
        row = await session.get(SignalDeliveryRow, delivery_id)
    assert row is not None
    assert row.outcome_detail is not None
    return row.outcome_detail


async def _opening_never_placed(world: World) -> None:
    """The venue knows none of these orders, the way ``OrderNotFound`` reaches a settle
    for an order that never landed. The attempts end ``FAILED``, nothing booked."""
    for venue in world.venues.values():
        venue.forget_orders()
    await _settle_all(world)


async def test_a_close_while_the_reservation_lives_waits_and_then_closes(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    queued = await _queued(world, closing)
    delivery_id, halves = queued[world.author]
    before = datetime.now(UTC)

    await _work(world, world.author, delivery_id, halves)

    assert len(world.venues[world.author].orders) == 1
    assert await _outcome(world, delivery_id) == ("ACCEPTED", None)
    assert await _polls(world, delivery_id) == [
        {"delivery_id": str(delivery_id), "halves": CLOSE, "poll": 1}
    ]
    assert (await _run_after(world, delivery_id, 1)) >= before + timedelta(seconds=5)

    await _settle_all(world)
    await _work(world, world.author, delivery_id, halves, 1)
    await _settle_all(world)

    assert len(world.venues[world.author].orders) == 2
    assert await _held(world, world.author) == 0
    assert len(await _polls(world, delivery_id)) == 1


async def test_a_close_after_the_reservation_expired_reaches_the_holder_and_closes(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    await _sweep_reservations(world)
    closing = await _signal(world, position_size="0", minutes=2)

    await _fan_out(world, closing)

    queued = await _queued(world, closing)
    assert set(queued) == {world.author, world.other}
    for user, (delivery_id, halves) in queued.items():
        await _work(world, user, delivery_id, halves)
        assert len(world.venues[user].orders) == 1
        assert len(await _polls(world, delivery_id)) == 1

    await _settle_all(world)
    for user, (delivery_id, halves) in queued.items():
        await _work(world, user, delivery_id, halves, 1)
    await _settle_all(world)

    assert await _held(world, world.author) == 0
    assert await _held(world, world.other) == 0


async def test_the_same_close_run_twice_seeds_one_poll_and_places_one_order(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """A crash between a run's commit and its job's ack runs it again."""
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    delivery_id, halves = (await _queued(world, closing))[world.author]

    await _work(world, world.author, delivery_id, halves)
    await _work(world, world.author, delivery_id, halves)

    assert len(await _polls(world, delivery_id)) == 1

    await _settle_all(world)
    await _work(world, world.author, delivery_id, halves, 1)
    await _work(world, world.author, delivery_id, halves, 1)

    assert len(world.venues[world.author].orders) == 2


async def test_the_wait_chain_outlives_its_second_poll(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Each run seeds the step after its own. Seeding one that already ran is a no-op,
    and the wait would end there with nothing logged."""
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    delivery_id, halves = (await _queued(world, closing))[world.author]

    await _work(world, world.author, delivery_id, halves)
    await _work(world, world.author, delivery_id, halves, 1)
    await _work(world, world.author, delivery_id, halves, 2)

    assert [poll["poll"] for poll in await _polls(world, delivery_id)] == [1, 2, 3]


async def test_a_close_of_an_opening_that_was_never_placed_ends_rejected(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    delivery_id, halves = (await _queued(world, closing))[world.author]
    await _opening_never_placed(world)

    with caplog.at_level(logging.WARNING):
        await _work(world, world.author, delivery_id, halves)

    assert await _outcome(world, delivery_id) == ("REJECTED", "NO_POSITION_TO_CLOSE")
    assert "the new side" not in await _detail(world, delivery_id)
    assert len(world.venues[world.author].orders) == 1
    assert await _polls(world, delivery_id) == []
    assert [
        record.levelno
        for record in caplog.records
        if "the opening was never placed" in record.getMessage()
    ] == [logging.WARNING]


async def test_a_reverse_of_an_opening_that_was_never_placed_says_the_new_side_stayed_shut(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    reverse = await _signal(world, position_size="-1", minutes=29)
    await _fan_out(world, reverse)
    delivery_id, halves = (await _queued(world, reverse))[world.author]
    await _opening_never_placed(world)

    await _work(world, world.author, delivery_id, halves)

    assert await _outcome(world, delivery_id) == ("REJECTED", "NO_POSITION_TO_CLOSE")
    assert "and the new side was not opened" in await _detail(world, delivery_id)
    assert len(world.venues[world.author].orders) == 1
    assert await _continue(world, set()) == []


async def test_a_position_booked_on_another_symbol_does_not_end_the_wait(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Booked is about THIS allocation: the user's ETH says nothing of their STX."""
    world = await _world(pg_session_factory)
    held_elsewhere = await _signal(world, position_size="1", minutes=0, symbol=ETH_ALERT)
    await _fan_out(world, held_elsewhere)
    delivery_id, halves = (await _queued(world, held_elsewhere))[world.author]
    await _work(world, world.author, delivery_id, halves)
    await _settle_all(world)
    await _opening_in_flight(world)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    delivery_id, halves = (await _queued(world, closing))[world.author]

    await _work(world, world.author, delivery_id, halves)

    assert len(await _polls(world, delivery_id)) == 1
    assert len(world.venues[world.author].orders) == 2


async def test_the_state_of_an_opening_belongs_to_its_user(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opening = await _opening_in_flight(world)
    allocation = (await _reservations(world, opening))[world.author].id

    async with world.factory() as session:
        states = SqlAlchemyOpeningStates(session)
        in_flight = await states.opening_state(world.author, allocation)
        of_another = await states.opening_state(world.other, allocation)
    await _settle_all(world)
    async with world.factory() as session:
        settled = await SqlAlchemyOpeningStates(session).opening_state(world.author, allocation)

    assert in_flight is not None
    assert (in_flight.status, in_flight.booked) == (ExecutionStatus.SUBMITTED, False)
    assert of_another is None
    assert settled is not None
    assert (settled.status, settled.booked) == (ExecutionStatus.FILLED, True)
    assert settled.created_at == in_flight.created_at


async def test_a_close_past_the_bound_ends_with_an_error_for_a_human(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    delivery_id, halves = (await _queued(world, closing))[world.author]
    await _attempts_aged(world, world.settings.close_after_open_timeout_seconds + 1)

    with caplog.at_level(logging.ERROR):
        await _work(world, world.author, delivery_id, halves)

    assert await _outcome(world, delivery_id) == ("REJECTED", "CONTINUATION_TIMED_OUT")
    assert len(world.venues[world.author].orders) == 1
    assert await _polls(world, delivery_id) == []
    assert any(
        record.levelno == logging.ERROR and "still in flight" in record.getMessage()
        for record in caplog.records
    )


async def test_a_reverse_waits_for_its_opening_and_then_closes_and_opens(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    # Recent: the continuation abandons a signal older than ten minutes.
    reverse = await _signal(world, position_size="-1", minutes=29)
    await _fan_out(world, reverse)
    delivery_id, halves = (await _queued(world, reverse))[world.author]
    assert halves == BOTH

    await _work(world, world.author, delivery_id, halves)

    assert len(world.venues[world.author].orders) == 1
    assert await _polls(world, delivery_id) == [
        {"delivery_id": str(delivery_id), "halves": BOTH, "poll": 1}
    ]

    await _settle_all(world)
    await _work(world, world.author, delivery_id, halves, 1)
    await _settle_all(world)
    assert await _continue(world, set()) == [delivery_id]
    await _settle_all(world)

    assert len(world.venues[world.author].orders) == 3
    assert await _held(world, world.author) < 0


async def test_a_reverse_on_a_pool_that_cannot_hold_the_new_side_reports_no_tail_early(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bare symbol is spot, and spot holds no short: this reverse ends flat, and says
    so once its close has run. A close that only waits has run nothing."""
    world = await _world(pg_session_factory)
    await _opening_in_flight(world, symbol="STXUSDT")
    reverse = await _signal(world, position_size="-1", minutes=2, symbol="STXUSDT")
    await _fan_out(world, reverse)
    delivery_id, halves = (await _queued(world, reverse))[world.author]

    with caplog.at_level(logging.WARNING):
        await _work(world, world.author, delivery_id, halves)

    assert await _outcome(world, delivery_id) == ("ACCEPTED", None)
    assert not [record for record in caplog.records if "partial" in record.getMessage()]


async def test_an_opening_in_flight_on_another_symbol_makes_no_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _signal(world, position_size="1", minutes=0)
    await _opening_in_flight(world, symbol=ETH_ALERT)
    await _sweep_reservations(world)
    closing = await _signal(world, position_size="0", minutes=2)

    await _fan_out(world, closing)

    assert await _queued(world, closing) == {}


async def test_an_opening_in_flight_of_another_user_makes_no_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The other subscriber's pool holds nothing, so only the author's order flies."""
    world = await _world(pg_session_factory)
    world.totals[world.other] = Decimal("0")
    await _opening_in_flight(world)
    await _sweep_reservations(world)
    closing = await _signal(world, position_size="0", minutes=2)

    await _fan_out(world, closing)

    assert set(await _queued(world, closing)) == {world.author}


async def test_an_opening_in_flight_of_another_strategy_makes_no_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    other_strategy = uuid4()
    await seed_strategy(
        world.factory, strategy_id=other_strategy, allowed_pairs=frozenset({"STXUSDT"})
    )
    async with world.factory() as session:
        pool = await ensure_pool(session, MARKET, user_id=OWNER_ID)
        await session.commit()
    await seeds.subscription(
        world.factory,
        OWNER_ID,
        other_strategy,
        pool,
        share="10",
        created_at=world.t0 - timedelta(days=1),
    )
    await _opening_in_flight(replace(world, strategy_id=other_strategy))
    await _sweep_reservations(world)
    await _signal(world, position_size="1", minutes=0)
    closing = await _signal(world, position_size="0", minutes=2)

    await _fan_out(world, closing)

    assert await _queued(world, closing) == {}


async def test_an_opening_that_ended_failed_makes_no_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    await _sweep_reservations(world)
    await _opening_never_placed(world)
    closing = await _signal(world, position_size="0", minutes=2)

    await _fan_out(world, closing)

    assert await _queued(world, closing) == {}


async def test_settling_an_opening_under_an_expired_reservation_books_its_fills(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """What the wait relies on: a fill landing past the TTL reaches the ledger."""
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    await _sweep_reservations(world)

    async with world.factory() as session:
        attempt = (
            await session.execute(
                select(ExecutionAttemptRow.id).where(ExecutionAttemptRow.user_id == world.author)
            )
        ).scalar_one()
    async with world.factory() as session:
        await _build_settle_execution(session, world.exchanges[world.author]).settle(
            world.author, attempt
        )

    assert await _held(world, world.author) > 0

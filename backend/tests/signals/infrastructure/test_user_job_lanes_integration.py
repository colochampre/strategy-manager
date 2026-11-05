"""One user's trading jobs run one at a time, other users' beside them (tasks.md G.7).

The worker runs lanes beside its first loop, and the claim keeps a user's deliveries,
continuations and settles in order: a job of those kinds is claimable only when no
other PENDING one of the same user comes before it. A job being worked still reads as
PENDING to every other claimer, because ``claim`` commits nothing until the job ends.

Real PostgreSQL, real fan-out. Each claim holds its own session open, the way the
worker holds a claim for as long as its handler runs.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager import main
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.shared.infrastructure.worker_runner import WorkerRunner
from strategy_manager.signals.infrastructure.fan_out_adapters import SqlAlchemySubscribers
from strategy_manager.signals.infrastructure.user_job_lanes import USER_JOB_LANES
from tests.signals.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.signals.infrastructure.test_close_waits_for_opening import (
    _opening_in_flight,
    _sweep_reservations,
)
from tests.signals.infrastructure.test_delivery_flow_integration import (
    MARKET,
    Factory,
    World,
    _fan_out,
    _queued,
    _settle_all,
    _signal,
    _work,
    _world,
)

pytestmark = pytest.mark.integration

WAIT_SECONDS = 10.0


async def _open_then_close(world: World) -> tuple[dict[UUID, UUID], dict[UUID, UUID]]:
    """Two signals of one strategy fanned out, none worked: each user has an opening
    delivery and, queued after it, a close. Returns ``user -> delivery`` for each."""
    opening = await _signal(world, position_size="1", minutes=1)
    await _fan_out(world, opening)
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    opens = {user: delivery for user, (delivery, _) in (await _queued(world, opening)).items()}
    closes = {user: delivery for user, (delivery, _) in (await _queued(world, closing)).items()}
    assert set(opens) == set(closes) == {world.author, world.other}
    return opens, closes


class _Claimer:
    """One claim held open on its own session, as a worker loop holds it."""

    def __init__(self, factory: Factory) -> None:
        self._session: AsyncSession = factory()
        self.queue = PostgresJobQueue(self._session, lanes=USER_JOB_LANES)

    async def claim(self, *, lane_only: bool = True) -> ClaimedJob | None:
        return await self.queue.claim(lane_only=lane_only)

    async def close(self) -> None:
        await self._session.close()


async def _claims(factory: Factory, count: int, *, lane_only: bool = True) -> list[Any]:
    """``count`` claims, each held open on its own session until the test ends."""
    claimers = [_Claimer(factory) for _ in range(count)]
    return [(claimer, await claimer.claim(lane_only=lane_only)) for claimer in claimers]


def _delivery(job: ClaimedJob | None) -> UUID | None:
    return None if job is None else UUID(str(job.payload["delivery_id"]))


async def _close_all(held: list[Any]) -> None:
    for claimer, _ in held:
        await claimer.close()


async def test_a_users_later_delivery_waits_while_the_earlier_one_is_worked(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opens, closes = await _open_then_close(world)

    held = await _claims(pg_session_factory, 3)
    try:
        claimed = [_delivery(job) for _, job in held]
        assert set(claimed[:2]) == set(opens.values())
        assert claimed[2] is None
    finally:
        await _close_all(held)


async def test_a_users_later_delivery_is_claimed_once_the_earlier_one_is_acknowledged(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opens, closes = await _open_then_close(world)

    first = _Claimer(pg_session_factory)
    other = _Claimer(pg_session_factory)
    later = _Claimer(pg_session_factory)
    try:
        worked = await first.claim()
        assert worked is not None
        user = next(u for u, d in opens.items() if d == _delivery(worked))
        held_other = await other.claim()
        assert _delivery(held_other) == opens[next(u for u in opens if u != user)]

        await first.queue.ack(worked.id)

        assert _delivery(await later.claim()) == closes[user]
    finally:
        for claimer in (first, other, later):
            await claimer.close()


async def test_a_failed_delivery_stops_holding_back_its_users_next_one(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """It goes back with a later ``run_after``, and the serial worker ran the next
    job meanwhile too."""
    world = await _world(pg_session_factory)
    opens, closes = await _open_then_close(world)

    first = _Claimer(pg_session_factory)
    try:
        worked = await first.claim()
        assert worked is not None
        user = next(u for u, d in opens.items() if d == _delivery(worked))
        await first.queue.fail(worked.id, "venue timed out")
    finally:
        await first.close()

    held = await _claims(pg_session_factory, 2)
    try:
        assert {_delivery(job) for _, job in held} == {
            closes[user],
            opens[next(u for u in opens if u != user)],
        }
    finally:
        await _close_all(held)


async def test_a_settle_holds_back_its_users_next_delivery(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _fan_out(world, opening)
    (author_open, halves) = (await _queued(world, opening))[world.author]
    await _work(world, world.author, author_open, halves)
    async with pg_session_factory() as session:
        await session.execute(
            update(JobRow)
            .where(JobRow.kind == JobKind.DELIVERY_PROCESS.value)
            .where(JobRow.payload["delivery_id"].astext == str(author_open))
            .values(status="DONE")
        )
        await session.execute(
            update(JobRow)
            .where(JobRow.kind == JobKind.EXECUTION_SETTLE.value)
            .values(run_after=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()
    closing = await _signal(world, position_size="0", minutes=2)
    await _fan_out(world, closing)
    author_close = (await _queued(world, closing))[world.author][0]

    held = await _claims(pg_session_factory, 4)
    try:
        kinds = [None if job is None else job.kind for _, job in held]
        assert kinds[0] is JobKind.EXECUTION_SETTLE
        assert author_close not in {_delivery(job) for _, job in held[1:]}
    finally:
        await _close_all(held)


async def _enqueue(factory: Factory, job: Job) -> None:
    async with factory() as session:
        await PostgresJobQueue(session).enqueue(job)
        await session.commit()


async def test_a_job_whose_user_cannot_be_read_is_left_to_the_first_loop_and_holds_back_the_rest(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """A continuation queued before C.8 names only its signal."""
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _enqueue(
        pg_session_factory,
        Job(
            kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
            payload={"signal_id": str(opening), "awaited_allocation_ids": [], "poll": 0},
            run_after=datetime.now(UTC) - timedelta(hours=1),
        ),
    )
    await _fan_out(world, opening)

    lane = await _claims(pg_session_factory, 1)
    try:
        assert lane[0][1] is None
    finally:
        await _close_all(lane)

    first = await _claims(pg_session_factory, 1, lane_only=False)
    try:
        job = first[0][1]
        assert job is not None
        assert job.kind is JobKind.SIGNAL_OPEN_AFTER_CLOSE
        assert "delivery_id" not in job.payload
    finally:
        await _close_all(first)


async def test_a_job_whose_user_cannot_be_read_waits_for_every_job_before_it(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _fan_out(world, opening)
    await _enqueue(
        pg_session_factory,
        Job(
            kind=JobKind.SIGNAL_OPEN_AFTER_CLOSE,
            payload={"signal_id": str(opening), "awaited_allocation_ids": [], "poll": 0},
        ),
    )

    held = await _claims(pg_session_factory, 2)
    first = await _claims(pg_session_factory, 1, lane_only=False)
    try:
        assert {_delivery(job) for _, job in held} == set(
            delivery for delivery, _ in (await _queued(world, opening)).values()
        )
        assert first[0][1] is None
    finally:
        await _close_all(held + first)


async def test_a_lane_claim_on_a_queue_with_no_lanes_is_refused(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(InvariantViolation, match="lanes"):
            await PostgresJobQueue(session).claim(lane_only=True)


async def test_a_lane_claims_no_job_of_the_first_loop(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _enqueue(
        pg_session_factory,
        Job(
            kind=JobKind.RESERVATION_SWEEP,
            payload={},
            run_after=datetime.now(UTC) - timedelta(hours=1),
        ),
    )
    await _fan_out(world, opening)

    lane = await _claims(pg_session_factory, 1)
    try:
        job = lane[0][1]
        assert job is not None
        assert job.kind is JobKind.DELIVERY_PROCESS
    finally:
        await _close_all(lane)

    first = await _claims(pg_session_factory, 1, lane_only=False)
    try:
        job = first[0][1]
        assert job is not None
        assert job.kind is JobKind.RESERVATION_SWEEP
    finally:
        await _close_all(first)


async def _until(done: Callable[[], bool], seconds: float = WAIT_SECONDS) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while not done():
        if loop.time() > deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def test_the_worker_works_another_user_while_one_users_delivery_is_paused(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The lock-hold harness: the paused handler keeps its claim open, as a live
    order would."""
    world = await _world(pg_session_factory)
    opens, closes = await _open_then_close(world)
    paused = opens[world.author]
    release = asyncio.Event()
    started: list[UUID] = []
    ended: list[UUID] = []

    async def handle(job: ClaimedJob) -> None:
        delivery = UUID(str(job.payload["delivery_id"]))
        started.append(delivery)
        if delivery == paused:
            await release.wait()
        ended.append(delivery)

    @asynccontextmanager
    async def queues() -> AsyncIterator[PostgresJobQueue]:
        async with pg_session_factory() as session:
            yield PostgresJobQueue(session, lanes=USER_JOB_LANES)

    runner = WorkerRunner(
        queue_factory=queues,
        handlers={JobKind.DELIVERY_PROCESS: handle},
        poll_interval_seconds=0.05,
        lanes=2,
    )
    stop = asyncio.Event()
    task = asyncio.create_task(runner.run_forever(stop))
    try:
        assert await _until(lambda: paused in started)
        assert await _until(lambda: closes[world.other] in ended)
        assert opens[world.other] in ended
        assert closes[world.author] not in started
        assert not task.done()

        release.set()

        assert await _until(lambda: closes[world.author] in ended)
        assert started.index(closes[world.author]) > started.index(paused)
    finally:
        release.set()
        stop.set()
        await asyncio.wait_for(task, WAIT_SECONDS)


async def test_the_workers_runner_runs_the_lanes_the_settings_give_through_the_user_rule(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    pool = PoolConfig(
        exchange=Exchange("bybit"),
        venue=Venue("usdt-m"),
        settlement_currency=Currency("USDT"),
        user_id=uuid4(),
        min_order_size=Decimal("1"),
    )
    runner = main.build_worker_runner([pool], session_factory_override=pg_session_factory)

    assert runner._lanes == get_settings().worker_delivery_lanes  # noqa: SLF001
    assert get_settings().worker_delivery_lanes == 4
    async with runner._queue_factory() as queue:  # noqa: SLF001
        assert queue._lanes is USER_JOB_LANES  # type: ignore[attr-defined]  # noqa: SLF001


class _SettlesAfterTheReservationRead:
    """A session that lets a settle commit right after ``_holds`` reads the
    reservations, the race a settle on a lane can now produce beside a fan-out."""

    def __init__(self, session: AsyncSession, settle: Callable[[], Awaitable[None]]) -> None:
        self._session = session
        self._settle = settle
        self.fired = False

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = await self._session.execute(statement, *args, **kwargs)
        if not self.fired and str(statement).startswith("SELECT reservations.id"):
            self.fired = True
            await self._settle()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


async def test_a_settle_committed_between_the_holders_reads_still_finds_the_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The reservation expired with the order in flight; the settle books the fill
    after the reservation read. Read ledger-first, the holder would be missed."""
    world = await _world(pg_session_factory)
    await _opening_in_flight(world)
    await _sweep_reservations(world)

    async with pg_session_factory() as session:
        racing = _SettlesAfterTheReservationRead(session, lambda: _settle_all(world))
        subscribers = SqlAlchemySubscribers(
            racing,  # type: ignore[arg-type]
            ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
        )
        found = await subscribers.live_holders(
            world.strategy_id, "STXUSDT", MARKET, world.t0 + timedelta(minutes=3)
        )

    assert racing.fired
    assert {holder.user_id for holder in found} == {world.author, world.other}


class _OpensBeforeTheDeliveryRead:
    """A session that lets every pending opening run to its end (reserved, filled,
    settled, its job acknowledged) just before the read of pending deliveries: the
    first state in the chain, a delivery on a lane beside a fan-out (G.D.1, A1)."""

    def __init__(self, session: AsyncSession, run: Callable[[], Awaitable[None]]) -> None:
        self._session = session
        self._run = run
        self.fired = False

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if not self.fired and str(statement).startswith("SELECT signal_deliveries.id"):
            self.fired = True
            await self._run()
        return await self._session.execute(statement, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


async def test_an_opening_run_to_its_end_during_the_holders_reads_still_finds_the_holder(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The pending delivery is read first, so whatever leaves it has already reached
    the reservation, the attempt or the ledger by the time those are read. Read last,
    an opening that ran in between was seen in no state, and its close reached nobody."""
    world = await _world(pg_session_factory)
    opening = await _signal(world, position_size="1", minutes=1)
    await _fan_out(world, opening)
    queued = await _queued(world, opening)

    async def run_every_opening() -> None:
        for user, (delivery_id, halves) in queued.items():
            await _work(world, user, delivery_id, halves)
        await _settle_all(world)
        async with pg_session_factory() as session:
            await session.execute(
                update(JobRow)
                .where(JobRow.kind == JobKind.DELIVERY_PROCESS.value)
                .values(status="DONE")
            )
            await session.commit()

    async with pg_session_factory() as session:
        racing = _OpensBeforeTheDeliveryRead(session, run_every_opening)
        subscribers = SqlAlchemySubscribers(
            racing,  # type: ignore[arg-type]
            ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
        )
        found = await subscribers.live_holders(
            world.strategy_id, "STXUSDT", MARKET, world.t0 + timedelta(minutes=3)
        )

    assert racing.fired
    assert {holder.user_id for holder in found} == {world.author, world.other}

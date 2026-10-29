"""A close that is fanned out before the opening's delivery has run (PR C verifier, B1).

The worker is serial and claims the oldest ``run_after`` first. A ``signal.process``
job is enqueued at ingest; the ``delivery.process`` jobs of a signal are enqueued
only when that signal's fan-out runs. So when an opening and its close are both
ingested before the worker reaches the opening (a backlog: a stopped worker during a
deploy, a restart, a slow job ahead), the order is: fan out the opening, fan out the
close, and only then work the opening's deliveries. The close must still close what
the opening opens, and must place nothing for a subscriber whose opening was refused.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from strategy_manager.execution.application.close_position import NothingRecordedYet
from strategy_manager.execution.infrastructure.exchange_registry import VenueExchangeRegistry
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.main import _build_settle_execution
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow
from tests.signals.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401
from tests.signals.infrastructure.test_delivery_flow_integration import (
    Factory,
    World,
    _fan_out,
    _held,
    _settle_all,
    _signal,
    _signal_outcome,
    _work,
    _world,
)

pytestmark = pytest.mark.integration


async def _enqueue_signal_job(world: World, signal_id: UUID) -> None:
    """What ingest does: one ``signal.process`` job, enqueued as the signal arrives."""
    async with world.factory() as session:
        await PostgresJobQueue(session).enqueue(
            Job(kind=JobKind.SIGNAL_PROCESS, payload={"signal_id": str(signal_id)})
        )
        await session.commit()


async def _owner_of_delivery(world: World, delivery_id: UUID) -> UUID:
    async with world.factory() as session:
        return (
            await session.execute(
                select(SignalDeliveryRow.user_id).where(SignalDeliveryRow.id == delivery_id)
            )
        ).scalar_one()


async def _run_job(world: World, job: ClaimedJob) -> None:
    if job.kind is JobKind.SIGNAL_PROCESS:
        await _fan_out(world, UUID(str(job.payload["signal_id"])))
    elif job.kind is JobKind.DELIVERY_PROCESS:
        delivery_id = UUID(str(job.payload["delivery_id"]))
        owner = await _owner_of_delivery(world, delivery_id)
        await _work(world, owner, delivery_id, job.payload.get("halves"))
    elif job.kind is JobKind.EXECUTION_SETTLE:
        attempt_id = UUID(str(job.payload["execution_attempt_id"]))
        async with world.factory() as session:
            owner = (
                await session.execute(
                    select(ExecutionAttemptRow.user_id).where(ExecutionAttemptRow.id == attempt_id)
                )
            ).scalar_one()
            await _build_settle_execution(
                session, VenueExchangeRegistry([world.venues[owner]])
            ).settle(owner, attempt_id)


async def _drain(world: World) -> list[str]:
    """Claims and runs jobs in the queue's own order, as the one worker runner does.
    A close that reaches the venue before the opening's fills settled raises
    ``NothingRecordedYet``; the runner then fails the job, which retries later."""
    ran: list[str] = []
    while True:
        async with world.factory() as session:
            job = await PostgresJobQueue(session).claim()
            await session.commit()
        if job is None:
            return ran
        ran.append(job.kind.value)
        try:
            await _run_job(world, job)
        except NothingRecordedYet as exc:
            ran.append(f"{job.kind.value}:retry")
            async with world.factory() as session:
                await PostgresJobQueue(session).fail(job.id, str(exc))
            continue
        async with world.factory() as session:
            await PostgresJobQueue(session).ack(job.id)


async def _retries_are_due(world: World) -> None:
    """Time passes: every job waiting out its retry delay is due now."""
    async with world.factory() as session:
        await session.execute(
            update(JobRow).where(JobRow.status == "PENDING").values(run_after=func.now())
        )
        await session.commit()


async def _work_the_backlog(world: World) -> list[str]:
    """The worker works through the backlog until nothing is left to run."""
    ran: list[str] = []
    for _ in range(4):
        ran += await _drain(world)
        await _settle_all(world)
        await _retries_are_due(world)
    return ran


async def _jobs_left(world: World) -> list[tuple[str, str]]:
    """``(kind, status)`` of every job that is not done."""
    async with world.factory() as session:
        result = await session.execute(
            select(JobRow.kind, JobRow.status).where(JobRow.status != "DONE")
        )
        return [(kind, status) for kind, status in result.all()]


async def _both_ingested_before_the_worker_runs(world: World) -> tuple[UUID, UUID]:
    opening = await _signal(world, position_size="1", minutes=1)
    closing = await _signal(world, position_size="0", minutes=2)
    await _enqueue_signal_job(world, opening)
    await _enqueue_signal_job(world, closing)
    return opening, closing


async def test_a_close_ingested_before_the_opening_was_worked_still_closes_it(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    world = await _world(pg_session_factory)
    _, closing = await _both_ingested_before_the_worker_runs(world)

    ran = await _work_the_backlog(world)

    # The queue's own order: both fan-outs run before either opening delivery.
    assert ran[:2] == ["signal.process", "signal.process"], ran
    # The strategy opened and then closed, so every subscriber must end flat.
    assert await _held(world, world.author) == 0
    assert await _held(world, world.other) == 0
    status, reason, _ = await _signal_outcome(world, closing)
    assert (status, reason) != ("REJECTED", "NO_POSITION_TO_CLOSE")
    assert await _jobs_left(world) == []


async def test_a_close_queued_behind_an_opening_that_is_then_refused_places_nothing(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The other subscriber's pool holds nothing, so their opening is refused. The
    close was delivered to them while that opening waited; it must end without an
    order and without a job left retrying."""
    world = await _world(pg_session_factory)
    world.totals[world.other] = Decimal("0")
    await _both_ingested_before_the_worker_runs(world)

    await _work_the_backlog(world)

    assert world.venues[world.other].orders == []
    assert await _held(world, world.other) == 0
    assert await _held(world, world.author) == 0
    assert len(world.venues[world.author].orders) == 2
    assert await _jobs_left(world) == []

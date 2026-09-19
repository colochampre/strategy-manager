"""Unit tests for the generic claim loop, exercised with a fake queue.

No database: ``WorkerRunner`` depends on ``JobQueuePort``, not on
``PostgresJobQueue`` directly, so its dispatch/ack/fail logic is fully
testable in isolation.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from strategy_manager.shared.application.job import ClaimedJob, JobKind
from strategy_manager.shared.infrastructure.worker_runner import WorkerRunner


class FakeJobQueue:
    def __init__(self, job_to_claim: ClaimedJob | None) -> None:
        self._job_to_claim = job_to_claim
        self.acked: list[object] = []
        self.failed: list[tuple[object, str]] = []

    async def claim(self) -> ClaimedJob | None:
        job, self._job_to_claim = self._job_to_claim, None
        return job

    async def ack(self, job_id: object) -> None:
        self.acked.append(job_id)

    async def fail(self, job_id: object, error: str) -> None:
        self.failed.append((job_id, error))


def _queue_factory(queue: FakeJobQueue) -> "AsyncIterator[FakeJobQueue]":
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeJobQueue]:
        yield queue

    return factory  # type: ignore[return-value]


async def test_run_once_returns_false_when_no_job_is_claimable() -> None:
    queue = FakeJobQueue(job_to_claim=None)
    runner = WorkerRunner(
        queue_factory=_queue_factory(queue), handlers={}, poll_interval_seconds=0.01
    )

    processed = await runner.run_once()

    assert processed is False


async def test_run_once_dispatches_to_the_registered_handler_and_acks_on_success() -> None:
    claimed = ClaimedJob(
        id=uuid4(), kind=JobKind.RESERVATION_SWEEP, payload={}, attempts=1, max_attempts=5
    )
    queue = FakeJobQueue(job_to_claim=claimed)
    handled: list[ClaimedJob] = []

    async def handler(job: ClaimedJob) -> None:
        handled.append(job)

    runner = WorkerRunner(
        queue_factory=_queue_factory(queue),
        handlers={JobKind.RESERVATION_SWEEP: handler},
        poll_interval_seconds=0.01,
    )

    processed = await runner.run_once()

    assert processed is True
    assert handled == [claimed]
    assert queue.acked == [claimed.id]
    assert queue.failed == []


async def test_run_once_fails_the_job_when_the_handler_raises() -> None:
    claimed = ClaimedJob(
        id=uuid4(), kind=JobKind.SIGNAL_PROCESS, payload={}, attempts=1, max_attempts=5
    )
    queue = FakeJobQueue(job_to_claim=claimed)

    async def handler(job: ClaimedJob) -> None:
        raise RuntimeError("exchange unreachable")

    runner = WorkerRunner(
        queue_factory=_queue_factory(queue),
        handlers={JobKind.SIGNAL_PROCESS: handler},
        poll_interval_seconds=0.01,
    )

    processed = await runner.run_once()

    assert processed is True
    assert queue.acked == []
    assert queue.failed == [(claimed.id, "exchange unreachable")]


async def test_run_once_fails_a_job_with_no_registered_handler() -> None:
    claimed = ClaimedJob(
        id=uuid4(), kind=JobKind.SIGNAL_PROCESS, payload={}, attempts=1, max_attempts=5
    )
    queue = FakeJobQueue(job_to_claim=claimed)
    runner = WorkerRunner(
        queue_factory=_queue_factory(queue), handlers={}, poll_interval_seconds=0.01
    )

    processed = await runner.run_once()

    assert processed is True
    assert queue.acked == []
    assert len(queue.failed) == 1
    assert queue.failed[0][0] == claimed.id


async def test_run_forever_runs_the_tick_hook_on_every_iteration() -> None:
    """The hook is how periodic maintenance rides the loop that already ticks,
    rather than a second task or a thread."""
    queue = FakeJobQueue(job_to_claim=None)
    runner = WorkerRunner(
        queue_factory=_queue_factory(queue), handlers={}, poll_interval_seconds=0.001
    )
    stop = asyncio.Event()
    ticks = 0

    async def tick() -> None:
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            stop.set()

    await runner.run_forever(stop, on_tick=tick)

    assert ticks == 3


async def test_a_failing_tick_hook_does_not_stop_the_loop() -> None:
    """Maintenance is not the job. A hook that cannot reach the database must
    not take down the worker that is still processing signals."""
    queue = FakeJobQueue(job_to_claim=None)
    runner = WorkerRunner(
        queue_factory=_queue_factory(queue), handlers={}, poll_interval_seconds=0.001
    )
    stop = asyncio.Event()
    calls = 0

    async def tick() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("database unreachable")
        stop.set()

    await runner.run_forever(stop, on_tick=tick)

    assert calls == 3

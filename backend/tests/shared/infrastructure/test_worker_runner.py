"""Unit tests for the generic claim loop, exercised with a fake queue.

No database: ``WorkerRunner`` depends on ``JobQueuePort``, not on
``PostgresJobQueue`` directly, so its dispatch/ack/fail logic is fully
testable in isolation.
"""

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

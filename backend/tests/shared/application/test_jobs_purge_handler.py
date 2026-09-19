"""``JobsPurgeHandler`` — the self-scheduling ``jobs.purge`` job.

Same shape as ``SweepHandler``/``BalanceSyncHandler``: no cron, each run
enqueues its own successor, and the successor is written only after the purge
returns without raising, so a transient failure retries instead of forking the
chain into two.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.jobs_purge_handler import JobsPurgeHandler
from strategy_manager.shared.application.purge_jobs import PurgeJobs, PurgeResult

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
INTERVAL = 86_400.0


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class SpyQueue:
    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> object:
        self.enqueued.append(job)
        return uuid4()


class StubPurgeJobs:
    def __init__(self, deleted: int = 0, raises: Exception | None = None) -> None:
        self._deleted = deleted
        self._raises = raises
        self.purges = 0

    async def purge(self) -> PurgeResult:
        self.purges += 1
        if self._raises is not None:
            raise self._raises
        return PurgeResult(deleted=self._deleted, capped=False)


def _claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), kind=JobKind.JOBS_PURGE, payload={}, attempts=1, max_attempts=5
    )


def _build(purge: StubPurgeJobs) -> tuple[JobsPurgeHandler, SpyQueue]:
    queue = SpyQueue()
    handler = JobsPurgeHandler(
        purge_jobs=purge,  # type: ignore[arg-type]
        queue=queue,
        clock=FrozenClock(),
        interval_seconds=INTERVAL,
    )
    return handler, queue


async def test_the_handler_runs_the_purge() -> None:
    purge = StubPurgeJobs(deleted=42)
    handler, _ = _build(purge)

    await handler.handle(_claimed_job())

    assert purge.purges == 1


async def test_the_handler_re_enqueues_itself_one_configured_interval_later() -> None:
    handler, queue = _build(StubPurgeJobs())

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1
    follow_up = queue.enqueued[0]
    assert follow_up.kind is JobKind.JOBS_PURGE
    assert follow_up.run_after == NOW + timedelta(seconds=INTERVAL)


async def test_the_re_enqueue_happens_even_when_nothing_was_deleted() -> None:
    """A purge that finds nothing is the normal case once retention is caught
    up. Re-enqueuing only after doing work would stop the chain the first day
    the table is already clean."""

    handler, queue = _build(StubPurgeJobs(deleted=0))

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1


async def test_a_failing_purge_does_not_re_enqueue() -> None:
    """``WorkerRunner`` fails and retries the claimed job on any handler
    exception. A successor enqueued before the purge succeeded would leave two
    live chains behind every transient error."""

    handler, queue = _build(StubPurgeJobs(raises=RuntimeError("db down")))

    with pytest.raises(RuntimeError):
        await handler.handle(_claimed_job())

    assert queue.enqueued == []


async def test_PurgeJobs_satisfies_the_handler_port() -> None:
    """Guards the stub above from drifting away from the real use case."""

    assert hasattr(PurgeJobs, "purge")

"""``SweepHandler`` — the ``reservation.sweep`` job handler that keeps itself
alive (design.md § Job handlers; tasks.md 6.6).

The sweeper has no external scheduler: it re-enqueues itself on every run. That
makes the re-enqueue the single point of failure for the whole mechanism — if
it is ever skipped, the sweeper stops permanently and nothing raises, so these
tests pin exactly when it happens.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from strategy_manager.allocation.application.expire_reservations import (
    ExpireReservations,
    SweepResult,
)
from strategy_manager.allocation.application.sweep_handler import SweepHandler
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind

NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
POLL_INTERVAL = 2.0


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class SpyQueue:
    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> object:
        self.enqueued.append(job)
        return uuid4()


class StubExpireReservations:
    def __init__(self, expired: int = 0, raises: Exception | None = None) -> None:
        self._expired = expired
        self._raises = raises
        self.sweeps = 0

    async def sweep(self) -> SweepResult:
        self.sweeps += 1
        if self._raises is not None:
            raise self._raises
        return SweepResult(expired=self._expired)


def _claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), kind=JobKind.RESERVATION_SWEEP, payload={}, attempts=1, max_attempts=5
    )


def _build(
    expire: StubExpireReservations,
) -> tuple[SweepHandler, SpyQueue]:
    queue = SpyQueue()
    handler = SweepHandler(
        expire_reservations=expire,  # type: ignore[arg-type]
        queue=queue,
        clock=FrozenClock(NOW),
        poll_interval_seconds=POLL_INTERVAL,
    )
    return handler, queue


async def test_the_handler_runs_the_sweep() -> None:
    expire = StubExpireReservations(expired=3)
    handler, _ = _build(expire)

    await handler.handle(_claimed_job())

    assert expire.sweeps == 1


async def test_the_handler_re_enqueues_itself_one_poll_interval_later() -> None:
    handler, queue = _build(StubExpireReservations())

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1
    follow_up = queue.enqueued[0]
    assert follow_up.kind is JobKind.RESERVATION_SWEEP
    assert follow_up.run_after == NOW + timedelta(seconds=POLL_INTERVAL)


async def test_the_re_enqueue_happens_even_when_nothing_expired() -> None:
    """An idle sweep is the normal case. Re-enqueuing only after doing work
    would stop the sweeper the first time the system is healthy."""

    handler, queue = _build(StubExpireReservations(expired=0))

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1


async def test_a_failing_sweep_does_not_re_enqueue() -> None:
    """``WorkerRunner`` fails and retries the claimed job on any handler
    exception. Enqueuing a successor before the sweep succeeded would leave two
    live chains behind every transient error, doubling on each failure."""

    handler, queue = _build(StubExpireReservations(raises=RuntimeError("db down")))

    with pytest.raises(RuntimeError):
        await handler.handle(_claimed_job())

    assert queue.enqueued == []


async def test_ExpireReservations_satisfies_the_handler_port() -> None:
    """Guards the stub above from drifting away from the real use case."""

    assert hasattr(ExpireReservations, "sweep")

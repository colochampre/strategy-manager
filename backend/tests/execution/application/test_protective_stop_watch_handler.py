"""``ProtectiveStopWatchHandler`` -- the self-scheduling ``protective_stop.watch`` job
(subscriber-safety SS.7).

It runs under ``DRY_RUN`` like the confirm job: a stop rests for a REAL position, and a real
position is watched whatever the brake says (CLAUDE.md rule 1), so there is no hard skip. Its
successor is enqueued after every pass that returns, including one where stops failed: the
queue has no backoff and ``max_attempts`` kills a chain outright, and a dead stop watcher is
silent. A failure of the pass itself propagates, so the job retries.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from strategy_manager.execution.application.protective_stop_watch_handler import (
    ProtectiveStopWatchHandler,
)
from strategy_manager.execution.application.watch_protective_stops import WatchResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind

NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
INTERVAL = 30.0


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class SpyQueue:
    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> object:
        self.enqueued.append(job)
        return uuid4()


class StubWatcher:
    def __init__(self, result: WatchResult | None = None, raises: Exception | None = None) -> None:
        self._result = result or WatchResult(read=3, fired=1)
        self._raises = raises
        self.calls = 0

    async def watch(self) -> WatchResult:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._result


def _job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), kind=JobKind.PROTECTIVE_STOP_WATCH, payload={}, attempts=1, max_attempts=5
    )


def _build(watcher: StubWatcher) -> tuple[ProtectiveStopWatchHandler, SpyQueue]:
    queue = SpyQueue()
    handler = ProtectiveStopWatchHandler(
        watcher=watcher, queue=queue, clock=FrozenClock(), interval_seconds=INTERVAL
    )
    return handler, queue


async def test_a_pass_runs_the_watcher_and_returns_what_it_found() -> None:
    watcher = StubWatcher(WatchResult(read=3, fired=1))
    handler, _ = _build(watcher)

    result = await handler.handle(_job())

    assert watcher.calls == 1
    assert result == WatchResult(read=3, fired=1)


async def test_the_successor_is_the_same_kind_one_interval_later() -> None:
    handler, queue = _build(StubWatcher())

    await handler.handle(_job())

    [successor] = queue.enqueued
    assert successor.kind is JobKind.PROTECTIVE_STOP_WATCH
    assert successor.run_after == NOW + timedelta(seconds=INTERVAL)
    assert successor.payload == {}


async def test_a_pass_where_stops_failed_still_schedules_the_next_one() -> None:
    handler, queue = _build(StubWatcher(WatchResult(read=2, failed=2)))

    await handler.handle(_job())

    assert len(queue.enqueued) == 1


async def test_a_pass_that_itself_fails_propagates_and_schedules_nothing() -> None:
    """The retry owns it; a worker restart or the revival re-seeds the chain if the retries
    run out."""
    handler, queue = _build(StubWatcher(raises=RuntimeError("database down")))

    with pytest.raises(RuntimeError, match="database down"):
        await handler.handle(_job())

    assert queue.enqueued == []

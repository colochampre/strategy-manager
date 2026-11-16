"""``ProtectiveStopWatchHandler``: the self-scheduling ``protective_stop.watch`` job
wrapping ``WatchProtectiveStops`` (subscriber-safety SS.7).

Self-scheduling like ``ReconciliationScanHandler``: no cron, no second process, each pass
enqueues its own successor, and ``RecurringJobSeeder`` / ``RecurringChainRevival`` keep the
chain alive.

**No DRY_RUN skip, unlike the reconciliation scan.** A stop rests for a REAL position, and a
real position is watched whatever the brake says: the brake is a brake, not the mode
(CLAUDE.md rule 1). Under the brake a user in SIMULATION has no RESTING stop to read at all
(a simulated opening records its level and places none), so a pass over nothing costs one
query.

**The successor is enqueued after every pass that returns**, including one where individual
stops failed (``WatchProtectiveStops`` logs those and never raises for them). The queue has
no backoff and ``max_attempts`` kills a chain outright, and a dead stop watcher is silent: a
fired stop would go unbooked until reconciliation raised it as a discrepancy. A failure of
the pass itself (the system query) propagates before the enqueue, so the job retries.
"""

import logging
from datetime import timedelta
from typing import Protocol

from strategy_manager.execution.application.watch_protective_stops import WatchResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort

logger = logging.getLogger(__name__)


class StopWatcherPort(Protocol):
    async def watch(self) -> WatchResult: ...


class ProtectiveStopWatchHandler:
    def __init__(
        self,
        watcher: StopWatcherPort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
    ) -> None:
        self._watcher = watcher
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds

    async def handle(self, job: ClaimedJob) -> WatchResult:
        result = await self._watcher.watch()
        logger.debug("protective stop watch %s: %s", job.id, result)
        await self._queue.enqueue(
            Job(
                kind=JobKind.PROTECTIVE_STOP_WATCH,
                run_after=self._clock.now() + timedelta(seconds=self._interval_seconds),
            )
        )
        return result

"""``JobsPurgeHandler``: the ``jobs.purge`` job handler.

Self-scheduling, for the same reasons as ``SweepHandler`` and
``BalanceSyncHandler``: no cron, no external scheduler, each run enqueues its
own successor. Both rules carried over from those handlers apply unchanged —
the successor is enqueued only after the purge returns without raising, so a
transient failure retries instead of forking the chain into two, and a purge
that found nothing to delete still re-enqueues.

This chain dying is the mildest of the three. A stale balance snapshot halts
trading and a dead reconciliation chain hides drift; a dead purge chain only
means the ``jobs`` table starts growing again, which is where it was before
this handler existed. It is still worth noticing, and a worker restart
re-seeds it (``RecurringJobSeeder``).

Note that the purge's own successor is one more row in the table it just
purged. At a daily interval that is 365 rows a year — nothing, and unlike the
sweeper's 2-second chain it is not a cadence that can quietly become the
dominant writer.
"""

from datetime import timedelta
from typing import Protocol

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort
from strategy_manager.shared.application.purge_jobs import PurgeResult


class PurgePort(Protocol):
    """What the handler needs from ``PurgeJobs``, declared here so the handler
    never depends on the use case's construction."""

    async def purge(self) -> PurgeResult: ...


class JobsPurgeHandler:
    def __init__(
        self,
        purge_jobs: PurgePort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
    ) -> None:
        self._purge_jobs = purge_jobs
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds

    async def handle(self, job: ClaimedJob) -> PurgeResult:
        del job  # retention is table-wide; the claimed job carries no payload
        result = await self._purge_jobs.purge()
        await self._queue.enqueue(
            Job(
                kind=JobKind.JOBS_PURGE,
                run_after=self._clock.now() + timedelta(seconds=self._interval_seconds),
            )
        )
        return result

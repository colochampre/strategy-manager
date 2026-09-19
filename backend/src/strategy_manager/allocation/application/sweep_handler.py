"""``SweepHandler``: the ``reservation.sweep`` job handler (design.md § Job
handlers).

There is no cron and no external scheduler — the sweeper keeps itself alive by
enqueuing its own successor on every run. Two consequences drive the code below:

1. **The successor is enqueued after the sweep succeeds, never before.**
   ``WorkerRunner`` catches any handler exception and fails the job so the queue
   retries it. If a successor were already enqueued, every transient error would
   leave two live chains, and the number of sweepers would double on each
   failure.
2. **An idle sweep still re-enqueues.** Finding nothing to expire is the normal,
   healthy case; re-enqueuing only after doing work would stop the sweeper the
   first time the system is behaving.

The chain still dies if a job exhausts ``max_attempts`` — the sweeper stops and
nothing raises. That is a monitoring concern this change does not solve; the
mitigation is that nothing depends on the sweep for *correctness*
(``sum_active`` already excludes expired reservations), only for bookkeeping.

That same fact is why ``interval_seconds`` is a SCHEDULING interval the caller
chooses, and pointedly not the worker's poll interval. It was the poll interval
once, and one value doing double duty made a bookkeeping chain run every two
seconds — 43,200 job rows a day, more than everything else combined. The
parameter is named for what it is so the substitution is not invited back.
"""

from datetime import timedelta
from typing import Protocol

from strategy_manager.allocation.application.expire_reservations import SweepResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort


class SweepPort(Protocol):
    """What the handler needs from ``ExpireReservations``, declared here so the
    handler never depends on the use case's construction."""

    async def sweep(self) -> SweepResult: ...


class SweepHandler:
    def __init__(
        self,
        expire_reservations: SweepPort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
    ) -> None:
        self._expire_reservations = expire_reservations
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds

    async def handle(self, job: ClaimedJob) -> SweepResult:
        del job  # the sweep is global; the claimed job carries no payload
        result = await self._expire_reservations.sweep()
        await self._queue.enqueue(
            Job(
                kind=JobKind.RESERVATION_SWEEP,
                run_after=self._clock.now() + timedelta(seconds=self._interval_seconds),
            )
        )
        return result

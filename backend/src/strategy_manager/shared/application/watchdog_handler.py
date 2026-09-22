"""``WatchdogHandler``: the ``watchdog.check`` job handler.

Self-scheduling, for the same reasons as ``SweepHandler``,
``BalanceSyncHandler`` and ``JobsPurgeHandler``: no cron, no external
scheduler, each run enqueues its own successor. Both rules carried over from
those handlers apply unchanged — the successor is enqueued only after the check
returns without raising, so a transient failure retries instead of forking the
chain into two, and a run that found nothing wrong still re-enqueues.

What this handler has that the others do not is a MEMORY. "What ended FAILED
since the previous run" needs a previous run, and a FAILED row is never purged,
so without a window every run would re-report every failure the deployment has
ever had. The chain carries that timestamp itself: each run hands its
``checked_at`` to its successor in the payload.

That is deliberately the only state — no table, no column, no migration, and
nothing to keep in sync with a restart. Losing it costs one window and never
the check: a seeded job (a first start, or ``RecurringJobSeeder`` reviving a
dead chain) carries an empty payload, and the use case falls back to one
interval of history. A malformed value is treated the same way rather than
raised on, because a watchdog that dies of its own bookkeeping is worse than
one that re-reads five minutes of jobs — this chain is the one nothing else is
watching.
"""

from datetime import datetime, timedelta
from typing import Any, Protocol

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort
from strategy_manager.shared.application.watchdog import WatchdogReport

SINCE_KEY = "since"


class WatchdogPort(Protocol):
    """What the handler needs from ``Watchdog``, declared here so the handler
    never depends on the use case's construction."""

    async def check(self, since: datetime | None, /) -> WatchdogReport: ...


class WatchdogHandler:
    def __init__(
        self,
        watchdog: WatchdogPort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
    ) -> None:
        self._watchdog = watchdog
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds

    async def handle(self, job: ClaimedJob) -> WatchdogReport:
        report = await self._watchdog.check(_since_of(job.payload))
        await self._queue.enqueue(
            Job(
                kind=JobKind.WATCHDOG_CHECK,
                payload={SINCE_KEY: report.checked_at.isoformat()},
                run_after=self._clock.now()
                + timedelta(seconds=self._interval_seconds),
            )
        )
        return report


def _since_of(payload: dict[str, Any]) -> datetime | None:
    """The previous run's ``checked_at``, or ``None`` when there is not a
    usable one.

    A naive value is rejected along with an unparseable one. Every clock in
    this system is timezone-aware, so a naive timestamp did not come from a
    previous run — and it would not fail here, it would fail deep inside the
    comparison the query makes with it.
    """
    raw = payload.get(SINCE_KEY)
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed

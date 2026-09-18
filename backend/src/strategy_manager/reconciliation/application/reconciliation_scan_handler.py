"""``ReconciliationScanHandler``: the ``reconciliation.scan`` job handler
wrapping ``ScanPools`` (design decisions 8, 11; ``scan_pools.py``'s own
docstring names this class as the one that owns both).

Self-scheduling, mirroring ``SweepHandler``/``BalanceSyncHandler``: no cron,
no external scheduler, each run enqueues its own successor. It owns exactly
the two behaviours ``ScanPools`` deliberately does NOT: the DRY_RUN hard
skip, and deciding when the successor is enqueued.

**The DRY_RUN skip (design decision 11).** Every fill recorded while
``DRY_RUN=true`` comes from ``FakeExchangeAdapter``, not a real venue.
Comparing that fake ledger against a REAL venue position call would
manufacture a discrepancy out of the rehearsal itself, so the SCAN is what
gets skipped here -- logged at WARNING so the skip is loud, never silent.
Skipping the job's own re-enqueue instead would be the silent version of
this bug: the chain would simply stop, and nothing would say why.

**The successor enqueue (design decision 8).** Deliberately UNLIKE
``BalanceSyncHandler``, which enqueues its successor only when ``sync()``
returns without raising, this handler reaches the enqueue call after EVERY
outcome that returns normally: a clean scan, a scan that had
``ScanPools`` swallow one or more per-pool ``VenuePositionReadError``s
internally (it already returns normally in that case -- see that module's
own docstring), and the DRY_RUN hard skip above. The queue has no backoff
and ``max_attempts`` kills a chain outright; ``balance.sync`` dying is LOUD
(a stale snapshot halts trading), but a dead reconciliation chain is
SILENT, so this handler refuses to let a degraded scan take the whole chain
down with it. A genuine programming error -- an unserved pool, a bug --
is NOT swallowed anywhere in this pipeline and propagates out of ``scan()``
before the enqueue call below is ever reached, so no successor is written
for it; a worker restart re-seeds the chain, which is the documented
recovery (``RecurringJobSeeder``).
"""

import logging
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from strategy_manager.reconciliation.application.scan_pools import ScanResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort

logger = logging.getLogger(__name__)


class ScanPoolsPort(Protocol):
    """What the handler needs from ``ScanPools``, declared here so the
    handler never depends on the use case's construction."""

    async def scan(self, scan_id: UUID) -> ScanResult: ...


class ReconciliationScanHandler:
    def __init__(
        self,
        scan_pools: ScanPoolsPort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
        dry_run: bool,
    ) -> None:
        self._scan_pools = scan_pools
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._dry_run = dry_run

    async def handle(self, job: ClaimedJob) -> ScanResult | None:
        if self._dry_run:
            logger.warning(
                "reconciliation scan skipped for job %s: DRY_RUN is enabled; "
                "comparing a fake ledger against a real venue position would "
                "manufacture a discrepancy out of the rehearsal itself",
                job.id,
            )
            result = None
        else:
            # The claimed job's own id, never a freshly minted one --
            # ``ScanPools.scan`` lands it verbatim as first_scan_id /
            # last_scan_id / resolved_by_scan_id (its own docstring).
            result = await self._scan_pools.scan(job.id)

        await self._queue.enqueue(
            Job(
                kind=JobKind.RECONCILIATION_SCAN,
                run_after=self._clock.now() + timedelta(seconds=self._interval_seconds),
            )
        )
        return result

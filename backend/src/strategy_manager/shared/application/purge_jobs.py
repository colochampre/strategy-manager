"""``PurgeJobs``: retention for the ``jobs`` table.

``PostgresJobQueue.ack`` sets ``status='DONE'`` and nothing has ever removed a
row, so the table only grows. The recurring chains alone write on the order of
10,000 rows a day, which is ~3.6M a year of finished work nobody reads. It has
not hurt yet because ``ix_jobs_claimable`` is PARTIAL on ``status='PENDING'``,
so claim latency does not degrade as history piles up behind it — the cost is
disk and bloat, paid silently.

**Only DONE rows are deleted, and only past the retention window.**

FAILED is never touched. A job that exhausted ``max_attempts`` goes FAILED and
its self-scheduling chain simply stops, with nothing raised and nothing
scheduled — ``recurring_jobs.py``'s docstring names restarting the worker as
the documented recovery. That row is the only surviving evidence the outage
happened. PENDING and CLAIMED are live work and are obviously out of scope; an
old ``updated_at`` on a CLAIMED row means a long-running job, not a finished
one.

Deleting DONE rows is safe for the two mechanisms that might look like they
depend on them, and neither does: duplicate webhooks are blocked by
``ux_signals_idempotency``, a UNIQUE on ``(strategy_id, idempotency_key)`` in
the ``signals`` table, and ``RecurringJobSeeder._has_live_job`` looks only for
PENDING or CLAIMED — deliberately, so a lingering DONE row can never block a
chain from being re-seeded.

**The run is bounded twice over.** Rows go in batches rather than in one
statement, and the run stops at a total cap. Production may already hold a
table far larger than one run should touch, and a single multi-million-row
DELETE inside one transaction is not something to schedule against a live
system. A backlog drains across successive runs instead; that is the intended
behaviour, not a shortfall.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from strategy_manager.shared.application.ports import (
    ClockPort,
    CommitPort,
    JobRetentionPort,
)

logger = logging.getLogger(__name__)

# One batch is one transaction's worth of row locks and WAL. 1,000 keeps each
# one short enough that a concurrent claim never waits on it, while still
# amortising the table scan that finds the rows.
DEFAULT_BATCH_SIZE = 1_000

# A ceiling on rows per run, so one run's duration stays predictable no matter
# how large the table was when retention was first switched on. At the steady
# state this system produces (~10,000 rows/day across every chain) a daily run
# has ten days of headroom, so the cap is never reached in normal operation and
# only bites when there is a genuine backlog — which is exactly when a single
# unbounded DELETE would be most damaging.
DEFAULT_MAX_ROWS_PER_RUN = 100_000


@dataclass(frozen=True, slots=True)
class PurgeResult:
    deleted: int
    capped: bool


class PurgeJobs:
    def __init__(
        self,
        retention: JobRetentionPort,
        clock: ClockPort,
        commit: CommitPort,
        retention_days: int,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_rows_per_run: int = DEFAULT_MAX_ROWS_PER_RUN,
    ) -> None:
        self._retention = retention
        self._clock = clock
        self._commit = commit
        self._retention_days = retention_days
        self._batch_size = batch_size
        self._max_rows_per_run = max_rows_per_run

    async def purge(self) -> PurgeResult:
        cutoff = self._clock.now() - timedelta(days=self._retention_days)
        deleted = 0

        while True:
            # Never ask for more than the run's remaining budget, so the cap is
            # a ceiling on rows rather than on whole batches.
            limit = min(self._batch_size, self._max_rows_per_run - deleted)
            batch = await self._retention.delete_done_before(cutoff, limit)
            # Committing per batch, not per run: an interrupted run keeps what
            # it already deleted, and no one transaction holds locks on the
            # whole cap.
            await self._commit.commit()
            deleted += batch

            if batch < limit:
                # Fewer rows than asked for means there are none left to find;
                # asking again would only pay for another scan.
                return PurgeResult(deleted=deleted, capped=False)

            if deleted >= self._max_rows_per_run:
                logger.warning(
                    "jobs.purge stopped at its per-run cap of %d rows; "
                    "%d-day retention has a backlog that will drain over "
                    "successive runs",
                    self._max_rows_per_run,
                    self._retention_days,
                )
                return PurgeResult(deleted=deleted, capped=True)

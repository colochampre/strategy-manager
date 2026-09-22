"""``PostgresJobHealth``: the watchdog's two questions about the ``jobs`` table.

Both are questions about ABSENCE, and both are answered by the WHERE clause
rather than by anything above it.

**A chain with nothing scheduled.** PENDING and CLAIMED are both ALIVE. The
same ``LIVE_STATUSES`` ``RecurringJobSeeder`` uses to decide whether to seed,
reused here on purpose: the seeder and the watchdog must agree on what "this
chain is running" means, or one of them will be healing a chain the other is
still alerting about.

Reading CLAIMED as dead would also be wrong twice over. A job being worked on
right now has not stopped, and ``PostgresJobQueue.claim`` deliberately does not
commit, so another session sees a claimed row as its last committed version —
PENDING — for as long as the job runs. Either way a healthy chain is never
momentarily empty: the handler commits its successor before the worker acks.

**What ended FAILED.** ``fail()`` writes FAILED only once ``max_attempts`` is
spent; a job that is merely retrying goes back to PENDING with its error
stored, and reporting that would alert on every transient fault the retry chain
exists to absorb. The window is bounded from below because ``jobs.purge``
deliberately never deletes a FAILED row — it is the only surviving trace of a
chain that died — so an unbounded query re-reports every failure the deployment
has ever had, every run, forever.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.watchdog import FailedJobs
from strategy_manager.shared.infrastructure.models import JobRow
from strategy_manager.shared.infrastructure.recurring_jobs import LIVE_STATUSES


class PostgresJobHealth:
    """Implements ``JobHealthPort`` against the ``jobs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def kinds_without_live_job(
        self, kinds: Sequence[JobKind]
    ) -> list[JobKind]:
        if not kinds:
            return []

        result = await self._session.execute(
            select(JobRow.kind)
            .where(
                JobRow.kind.in_([kind.value for kind in kinds]),
                JobRow.status.in_(LIVE_STATUSES),
            )
            .distinct()
        )
        alive = {str(kind) for kind in result.scalars().all()}
        # The caller's order, not the database's: the message names the chains
        # in the order they were configured, which is the order an operator
        # reads them in everywhere else.
        return [kind for kind in kinds if kind.value not in alive]

    async def failures_since(self, since: datetime) -> list[FailedJobs]:
        """``since`` is INCLUSIVE. It is the previous run's own ``checked_at``,
        so an exclusive bound would silently drop a job that failed in the same
        instant that run read the table."""
        result = await self._session.execute(
            select(JobRow.kind, func.count().label("failures"))
            .where(JobRow.status == "FAILED", JobRow.updated_at >= since)
            .group_by(JobRow.kind)
            .order_by(JobRow.kind)
        )
        return [
            FailedJobs(kind=str(row.kind), count=int(row.failures))
            for row in result.all()
        ]

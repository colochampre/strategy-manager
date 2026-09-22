"""Seeds the first job of every self-scheduling chain.

``reservation.sweep`` and ``balance.sync`` stay alive by enqueuing their own
successor, which means neither ever starts on its own. Something has to put
the first job on the queue — and it has to do that exactly once per live
chain, on every worker start, forever.

Naive seeding at startup forks the chain in two on the second start, and in
four on the third. So the seeder asks what already exists: a chain with a
PENDING or CLAIMED job is alive and is left alone.

That test also revives a chain instead of only protecting one. If a job
exhausts ``max_attempts`` it goes FAILED and the chain is over, silently, with
nothing scheduled. No live job means the next seeding pass enqueues a fresh
one.

A worker start used to be the only pass there was, so restarting the worker was
the whole recovery procedure — and nothing restarts the worker. See
``RecurringChainRevival`` at the bottom of this module for the cadence that
made recovery automatic, and for why it is the loud kind.

``dedupe_key`` deliberately is not the mechanism here: its unique index spans
the whole table for all time, so the DONE seed row from the first start would
block every later re-seed and a dead chain could never come back.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort
from strategy_manager.shared.infrastructure.models import JobRow

logger = logging.getLogger(__name__)

RECURRING_KINDS: tuple[JobKind, ...] = (
    JobKind.RESERVATION_SWEEP,
    JobKind.BALANCE_SYNC,
    JobKind.RECONCILIATION_SCAN,
    # Retention for this very table. It is seeded like any other chain
    # precisely because it is one: nothing deletes a DONE row unless this job
    # is alive, so a purge chain that died must come back on a worker restart
    # the same way the others do.
    JobKind.JOBS_PURGE,
    # The periodic health check. Seeded like any other chain, and it checks
    # itself along with the rest — harmlessly, since the job running the check
    # is CLAIMED while it runs and so counts as live. What it cannot do is
    # notice its own DEATH; see ``shared.application.watchdog``'s docstring for
    # why only something outside this process can.
    JobKind.WATCHDOG_CHECK,
)

LIVE_STATUSES: tuple[str, ...] = ("PENDING", "CLAIMED")

# Single-argument pg_advisory_xact_lock. PostgreSQL keeps the one-argument and
# two-argument advisory lock spaces separate, so this can never collide with a
# pool lock, which uses the two-argument form.
_SEED_LOCK_NAME = "strategy_manager.recurring_jobs_seed"


class RecurringJobSeeder:
    """Ensures each recurring chain has exactly one live job."""

    def __init__(self, session: AsyncSession, queue: JobQueuePort) -> None:
        self._session = session
        self._queue = queue

    async def seed(
        self, kinds: Sequence[JobKind] = RECURRING_KINDS
    ) -> list[JobKind]:
        """Returns the kinds actually seeded — empty when every chain was
        already alive.

        Serialized behind an advisory lock so two workers starting at the same
        moment cannot both observe an empty queue and both seed, which is the
        exact chain-doubling this class exists to prevent.
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:name)::bigint)"),
            {"name": _SEED_LOCK_NAME},
        )

        seeded: list[JobKind] = []
        for kind in kinds:
            if await self._has_live_job(kind):
                continue
            await self._queue.enqueue(Job(kind=kind))
            seeded.append(kind)

        await self._session.commit()
        return seeded

    async def _has_live_job(self, kind: JobKind) -> bool:
        result = await self._session.execute(
            select(JobRow.id)
            .where(JobRow.kind == kind.value, JobRow.status.in_(LIVE_STATUSES))
            .limit(1)
        )
        return result.first() is not None


SeedCallable = Callable[[], Awaitable[Sequence[JobKind]]]


class RecurringChainRevival:
    """Re-runs the seeder on a cadence from inside the worker's claim loop.

    The docstring at the top of this module says a worker restart is the
    documented recovery for a dead chain. It was also the ONLY one, and nothing
    restarts the worker: on 2026-09-18 ``balance.sync`` died and stayed dead for
    19 hours. This closes that by asking the same question every few minutes
    instead of once per process.

    Re-running is safe by construction, not by luck: ``seed()`` takes the
    advisory lock and skips any chain with a PENDING or CLAIMED job, so a
    healthy queue is left exactly as it was found.

    **The logging asymmetry is the point of this class, not an accident of it.**
    The two ``seed()`` calls look identical and mean opposite things. Seeding at
    startup is ordinary — the chains have to begin somewhere — so the worker
    logs that at INFO. A chain seeded HERE was alive when the process began and
    is not any more, which means it exhausted ``max_attempts`` and nothing was
    scheduled. Healing that silently would turn a loud failure into an invisible
    one, which is the opposite of what a self-healing loop is for, so a revival
    is a WARNING that names the kinds. A re-seed that finds everything alive is
    the normal case and says nothing at all.
    """

    def __init__(
        self,
        seed: SeedCallable,
        clock: ClockPort,
        interval_seconds: float,
        last_seeded_at: datetime,
    ) -> None:
        self._seed = seed
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._last_seeded_at = last_seeded_at

    async def revive_if_due(self) -> list[JobKind]:
        """Returns the kinds revived — empty when the interval has not elapsed
        or when every chain was already alive."""
        now = self._clock.now()
        if (now - self._last_seeded_at).total_seconds() < self._interval_seconds:
            return []

        self._last_seeded_at = now
        revived = list(await self._seed())
        if revived:
            logger.warning(
                "revived dead recurring chain(s): %s. Each one had exhausted its "
                "retries and had nothing scheduled, so it had stopped running "
                "entirely — check the FAILED rows in the jobs table for why.",
                [kind.value for kind in revived],
            )
        return revived

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
nothing scheduled. No live job means the next worker start seeds a fresh one,
which makes restarting the worker the documented recovery for a dead chain.

``dedupe_key`` deliberately is not the mechanism here: its unique index spans
the whole table for all time, so the DONE seed row from the first start would
block every later re-seed and a dead chain could never come back.
"""

from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import JobQueuePort
from strategy_manager.shared.infrastructure.models import JobRow

RECURRING_KINDS: tuple[JobKind, ...] = (
    JobKind.RESERVATION_SWEEP,
    JobKind.BALANCE_SYNC,
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

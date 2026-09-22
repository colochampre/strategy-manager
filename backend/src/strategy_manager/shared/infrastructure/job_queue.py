"""PostgreSQL-backed job queue: ``FOR UPDATE SKIP LOCKED`` claim/ack/fail.

``claim()`` deliberately does not commit: the row lock and the uncommitted
``status='CLAIMED'`` write must stay open for the lifetime of the caller's
session so that a crashed connection rolls both back automatically, releasing
the job for reclaim (spec: job-queue § Crash Reclaim). ``ack``/``fail`` commit,
finalizing the outcome.

``fail()`` also pushes ``run_after`` forward. It used to leave that column
alone, which meant a retry was claimable on the very next poll and
``max_attempts`` could be spent inside half a minute — see
``config.py``'s ``job_retry_backoff_base_seconds`` for the incident that
arithmetic came from.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.models import JobRow

# Mirror ``Settings.job_retry_backoff_*``. They are duplicated rather than read
# here because this adapter must not reach for configuration itself: the
# composition roots inject the real values (``main.py``, ``worker.py``). These
# keep the dozens of existing construction sites — most of them tests that only
# enqueue or claim — working unchanged.
DEFAULT_BACKOFF_BASE_SECONDS = 30.0
DEFAULT_BACKOFF_MAX_SECONDS = 600.0


class PostgresJobQueue:
    """Implements ``JobQueuePort`` against the ``jobs`` table."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: ClockPort | None = None,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
    ) -> None:
        self._session = session
        self._clock: ClockPort = clock or SystemClock()
        self._backoff_base_seconds = backoff_base_seconds
        self._backoff_max_seconds = backoff_max_seconds

    async def enqueue(self, job: Job) -> UUID:
        stmt = (
            insert(JobRow)
            .values(
                kind=job.kind.value,
                payload=job.payload,
                run_after=job.run_after or self._clock.now(),
                max_attempts=job.max_attempts,
                dedupe_key=job.dedupe_key,
            )
            .returning(JobRow.id)
        )
        result = await self._session.execute(stmt)
        job_id: UUID = result.scalar_one()
        return job_id

    async def enqueue_unique(self, job: Job) -> UUID:
        """``INSERT ... ON CONFLICT (dedupe_key) DO NOTHING RETURNING id``,
        with a ``SELECT`` fallback for the existing row's id.

        ``RETURNING`` yields no row on a no-op conflict, so a caller reading
        only the ``INSERT`` result would see nothing on exactly the call
        meant to make retrying safe (design.md § S5, the per-poll
        ``dedupe_key`` chain). Never commits, exactly like ``enqueue`` above
        -- design.md § S5 needs the seed committed atomically with the
        caller's own write (a close attempt) inside the SAME transaction;
        committing here would split that write in two.
        """
        if job.dedupe_key is None:
            raise InvariantViolation("enqueue_unique requires a dedupe_key")

        stmt = (
            pg_insert(JobRow)
            .values(
                kind=job.kind.value,
                payload=job.payload,
                run_after=job.run_after or self._clock.now(),
                max_attempts=job.max_attempts,
                dedupe_key=job.dedupe_key,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(JobRow.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()
        if row is not None:
            job_id: UUID = row.id
            return job_id

        existing = await self._session.execute(
            select(JobRow.id).where(JobRow.dedupe_key == job.dedupe_key)
        )
        return existing.scalar_one()

    async def claim(self) -> ClaimedJob | None:
        now = self._clock.now()
        claimable = (
            select(JobRow.id)
            .where(JobRow.status == "PENDING", JobRow.run_after <= now)
            .order_by(JobRow.run_after, JobRow.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        stmt = (
            update(JobRow)
            .where(JobRow.id.in_(claimable))
            .values(status="CLAIMED", claimed_at=now, attempts=JobRow.attempts + 1)
            .returning(
                JobRow.id, JobRow.kind, JobRow.payload, JobRow.attempts, JobRow.max_attempts
            )
        )
        result = await self._session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        return ClaimedJob(
            id=row.id,
            kind=JobKind(row.kind),
            payload=row.payload,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
        )

    async def ack(self, job_id: UUID) -> None:
        await self._session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(status="DONE", updated_at=self._clock.now())
        )
        await self._session.commit()

    async def fail(self, job_id: UUID, error: str) -> None:
        result = await self._session.execute(
            select(JobRow.attempts, JobRow.max_attempts).where(JobRow.id == job_id)
        )
        row = result.one()
        now = self._clock.now()
        retrying = row.attempts < row.max_attempts

        values: dict[str, object] = {
            "status": "PENDING" if retrying else "FAILED",
            "last_error": error,
            "updated_at": now,
        }
        if retrying:
            # A retry waits; an exhausted job does not get its ``run_after``
            # rewritten, because nothing will ever claim it again and the
            # column is the only record of when it was originally due.
            values["run_after"] = now + timedelta(seconds=self._retry_delay(row.attempts))

        await self._session.execute(
            update(JobRow).where(JobRow.id == job_id).values(**values)
        )
        await self._session.commit()

    def _retry_delay(self, attempts: int) -> float:
        """``min(base * 2 ** (attempts - 1), cap)``.

        ``attempts`` was already incremented by ``claim()``, so the first
        failure arrives here as 1 and waits exactly one base delay.

        The exponent is clamped because ``max_attempts`` is a per-job column
        with no ceiling: past about 1,024 the doubling overflows a float, and an
        OverflowError raised here would escape ``fail()`` and take the claim
        loop down with it. Any exponent that large is orders of magnitude past
        the cap anyway, so clamping changes no reachable answer.
        """
        growth = 2.0 ** min(attempts - 1, 32)
        return min(self._backoff_base_seconds * growth, self._backoff_max_seconds)

"""PostgreSQL-backed job queue: ``FOR UPDATE SKIP LOCKED`` claim/ack/fail.

``claim()`` deliberately does not commit: the row lock and the uncommitted
``status='CLAIMED'`` write must stay open for the lifetime of the caller's
session so that a crashed connection rolls both back automatically, releasing
the job for reclaim (spec: job-queue § Crash Reclaim). ``ack``/``fail`` commit,
finalizing the outcome.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.infrastructure.models import JobRow


class PostgresJobQueue:
    """Implements ``JobQueuePort`` against the ``jobs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, job: Job) -> UUID:
        stmt = (
            insert(JobRow)
            .values(
                kind=job.kind.value,
                payload=job.payload,
                run_after=job.run_after or datetime.now(UTC),
                max_attempts=job.max_attempts,
                dedupe_key=job.dedupe_key,
            )
            .returning(JobRow.id)
        )
        result = await self._session.execute(stmt)
        job_id: UUID = result.scalar_one()
        return job_id

    async def claim(self) -> ClaimedJob | None:
        now = datetime.now(UTC)
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
            .values(status="DONE", updated_at=datetime.now(UTC))
        )
        await self._session.commit()

    async def fail(self, job_id: UUID, error: str) -> None:
        result = await self._session.execute(
            select(JobRow.attempts, JobRow.max_attempts).where(JobRow.id == job_id)
        )
        row = result.one()
        next_status = "PENDING" if row.attempts < row.max_attempts else "FAILED"
        await self._session.execute(
            update(JobRow)
            .where(JobRow.id == job_id)
            .values(status=next_status, last_error=error, updated_at=datetime.now(UTC))
        )
        await self._session.commit()

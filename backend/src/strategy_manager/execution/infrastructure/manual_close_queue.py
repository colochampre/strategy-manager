"""Queues the ``execution.manual_close`` job for one allocation of one user's: what "Close now"
does (``POST /api/positions/{allocation_id}/close``) and what deleting an account does for each
simulated position it leaves open (account-deletion L9). One definition, so the two queue the
same job under the same key.

- If the latest close of the allocation is SUBMITTED, nothing is queued: it is in flight.
- Otherwise the job is queued with ``enqueue_unique``. Its key is the allocation plus the id of
  the allocation's latest close attempt (or ``none``): a second ask before the job ran queues
  nothing new, and a retry after a FAILED close, whose attempt id is new, queues again. A
  finished job keeps its key until the purge, which is why the attempt id is part of it.

Nothing here commits: the caller's transaction does.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue


@dataclass(frozen=True, slots=True)
class QueuedClose:
    status: Literal["QUEUED", "ALREADY_IN_FLIGHT"]
    # The close in flight, for ``ALREADY_IN_FLIGHT``.
    attempt_id: UUID | None
    # Whether a new job row went in; ``False`` when one waiting or running already had the key.
    inserted: bool


async def queue_manual_close(
    session: AsyncSession, user_id: UUID, allocation_id: UUID
) -> QueuedClose:
    latest = await SqlAlchemyExecutionAttemptRepository(session).latest_close_for(
        user_id, allocation_id
    )
    if latest is not None and latest.status is ExecutionStatus.SUBMITTED:
        return QueuedClose(status="ALREADY_IN_FLIGHT", attempt_id=latest.id, inserted=False)
    dedupe_key = f"manual_close:{allocation_id}:{latest.id if latest else 'none'}"
    # A finished job keeps its key until the purge, days later. One that ended without an
    # attempt (no key could sign, the ledger was not settled yet) would leave the key
    # unchanged and the button dead, so only a job still waiting or running dedupes.
    await session.execute(
        text(
            "UPDATE jobs SET dedupe_key = NULL "
            "WHERE dedupe_key = :key AND status IN ('DONE', 'FAILED')"
        ),
        {"key": dedupe_key},
    )
    _, inserted = await PostgresJobQueue(session).enqueue_unique(
        Job(
            kind=JobKind.MANUAL_CLOSE,
            payload={"user_id": str(user_id), "allocation_id": str(allocation_id)},
            dedupe_key=dedupe_key,
        )
    )
    return QueuedClose(status="QUEUED", attempt_id=None, inserted=inserted)

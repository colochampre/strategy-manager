"""``POST /api/positions/{allocation_id}/close``: a user asks to close one of their own open
positions from the panel (subscriber-safety SS.9, spec ``safety-close``, "A user can close their
own position from the panel").

**The API never places the order.** An order needs the user's key, and only the worker opens a
key (CLAUDE.md, "Credentials"). So this route checks, enqueues one ``execution.manual_close`` job
and answers 202; the worker closes through ``ClosePosition`` with that user's own exchanges.

- The allocation must be the signed-in user's own and still hold a position. Another user's id,
  an unknown one and a flat one all answer 404, and enqueue nothing: the three are told apart by
  nobody, so the route is no oracle for other users' allocations.
- If the latest close of the allocation is SUBMITTED the route answers 202
  ``ALREADY_IN_FLIGHT`` and enqueues nothing.
- Otherwise it enqueues the job with ``enqueue_unique``. Its key is the allocation plus the id of
  the allocation's latest close attempt (or ``none``): a second click before the job ran
  enqueues nothing new, and a retry after a FAILED close, whose attempt id is new, enqueues
  again. A finished job keeps its key until the purge, which is why the attempt id is part of it.

It uses the plain writable session: the open positions listing next to it reads a snapshot, and a
route that enqueues cannot.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.execution.infrastructure.stopped_positions_reader import (
    SqlAlchemyStoppedPositionsReader,
)
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.job_queue import PostgresJobQueue

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[User, Depends(current_user)]


class ManualCloseResponse(BaseModel):
    status: Literal["QUEUED", "ALREADY_IN_FLIGHT"]


@router.post("/{allocation_id}/close", status_code=202, response_model=ManualCloseResponse)
async def close_now(
    allocation_id: UUID, session: SessionDep, user: CurrentUserDep
) -> ManualCloseResponse:
    held = await SqlAlchemyStoppedPositionsReader(session).position_of(user.id, allocation_id)
    if held is None or held.net_base == 0:
        raise HTTPException(status_code=404, detail="position not found")

    latest = await SqlAlchemyExecutionAttemptRepository(session).latest_close_for(
        user.id, allocation_id
    )
    if latest is not None and latest.status is ExecutionStatus.SUBMITTED:
        logger.info(
            "close now refused as already in flight: user=%s allocation=%s attempt=%s",
            str(user.id)[:8],
            allocation_id,
            latest.id,
        )
        return ManualCloseResponse(status="ALREADY_IN_FLIGHT")

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
            payload={"user_id": str(user.id), "allocation_id": str(allocation_id)},
            dedupe_key=dedupe_key,
        )
    )
    await session.commit()
    logger.info(
        "close now accepted: user=%s allocation=%s queued=%s",
        str(user.id)[:8],
        allocation_id,
        inserted,
    )
    return ManualCloseResponse(status="QUEUED")

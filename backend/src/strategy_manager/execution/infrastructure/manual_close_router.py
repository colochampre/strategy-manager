"""``POST /api/positions/{allocation_id}/close``: a user asks to close one of their own open
positions from the panel (subscriber-safety SS.9, spec ``safety-close``, "A user can close their
own position from the panel").

**The API never places the order.** An order needs the user's key, and only the worker opens a
key (CLAUDE.md, "Credentials"). So this route checks, enqueues one ``execution.manual_close`` job
and answers 202; the worker closes through ``ClosePosition`` with that user's own exchanges.

- The allocation must be the signed-in user's own and still hold a position. Another user's id,
  an unknown one and a flat one all answer 404, and enqueue nothing: the three are told apart by
  nobody, so the route is no oracle for other users' allocations.
- Otherwise ``queue_manual_close`` queues the job, or answers 202 ``ALREADY_IN_FLIGHT`` and
  queues nothing while the latest close of the allocation is SUBMITTED. Its docstring has the
  dedupe key; deleting an account queues the same job through it.

It uses the plain writable session: the open positions listing next to it reads a snapshot, and a
route that enqueues cannot.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.manual_close_queue import queue_manual_close
from strategy_manager.execution.infrastructure.stopped_positions_reader import (
    SqlAlchemyStoppedPositionsReader,
)
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.shared.db import get_session

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

    queued = await queue_manual_close(session, user.id, allocation_id)
    if queued.status == "ALREADY_IN_FLIGHT":
        logger.info(
            "close now refused as already in flight: user=%s allocation=%s attempt=%s",
            str(user.id)[:8],
            allocation_id,
            queued.attempt_id,
        )
        return ManualCloseResponse(status="ALREADY_IN_FLIGHT")
    await session.commit()
    logger.info(
        "close now accepted: user=%s allocation=%s queued=%s",
        str(user.id)[:8],
        allocation_id,
        queued.inserted,
    )
    return ManualCloseResponse(status="QUEUED")

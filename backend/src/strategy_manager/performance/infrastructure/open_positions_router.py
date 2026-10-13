"""``GET /api/positions/open``: every open position and every in-flight order of
the system (design addendum "open positions", decision 65, section F).

This is the STUB of task op.1.1. The snapshot dependency is a pass-through that
yields a plain session, and the body carries only the ids the snapshot test (T6)
needs. The route is not registered in ``main.py`` yet.

Authentication is attached to the ROUTER, as on every admin router.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.performance.application.ports import OpenStateSourcePort
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_snapshot_session(session: SessionDep) -> AsyncIterator[AsyncSession]:
    """The session of ONE request. Task op.1.1: a pass-through."""
    yield session


SnapshotSessionDep = Annotated[AsyncSession, Depends(get_snapshot_session)]


def get_open_state_source(session: SnapshotSessionDep) -> OpenStateSourcePort:
    return SqlAlchemyModeOriginReader(session)


OpenStateDep = Annotated[OpenStateSourcePort, Depends(get_open_state_source)]


class OpenPositionsBody(BaseModel):
    positions: list[UUID]
    orders: list[UUID]


@router.get("/open", response_model=OpenPositionsBody)
async def read_open_positions(state: OpenStateDep) -> OpenPositionsBody:
    answer = await ReadOpenPositions(state).read()
    return OpenPositionsBody(
        positions=[position.allocation_id for position in answer.opened],
        orders=[order.attempt_id for order in answer.in_flight],
    )

"""``GET /api/positions/open``: every open position and every in-flight order of
the system (design addendum "open positions", decision 65, section F).

This is still a STUB: the body carries only the ids the snapshot test (T6) needs,
and the facts and disagreement sources are placeholders. The snapshot dependency
is real (a read-only ``REPEATABLE READ`` transaction). The route is not
registered in ``main.py`` yet.

Authentication is attached to the ROUTER, as on every admin router.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.performance.application.ports import (
    OpenStateSourcePort,
    PositionFacts,
    SubmittedOrder,
)
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.domain.open_position import DiscrepancyRow
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_snapshot_session(session: SessionDep) -> AsyncIterator[AsyncSession]:
    """The session of ONE request, in a read-only ``REPEATABLE READ`` transaction.

    The statement must be the transaction's FIRST: PostgreSQL refuses to change
    the isolation level after a query ("must be called before any query"), and
    that refusal propagates as a 500 and the panel's error state. A snapshot that
    is not in force is never silently dropped (design K row 15). The use case and
    the ports know nothing of this."""
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    yield session


SnapshotSessionDep = Annotated[AsyncSession, Depends(get_snapshot_session)]


def get_open_state_source(session: SnapshotSessionDep) -> OpenStateSourcePort:
    return SqlAlchemyModeOriginReader(session)


OpenStateDep = Annotated[OpenStateSourcePort, Depends(get_open_state_source)]


class _NoFactsYet:
    """PLACEHOLDER until the facts adapter exists (tasks op.1.21 and op.1.22):
    it answers nothing, so every row is built from the reader's own element. The
    route is not registered in ``main.py``, so nothing serves this."""

    async def position_facts(self, allocation_ids: Sequence[UUID]) -> Mapping[UUID, PositionFacts]:
        return {}

    async def submitted_orders(self) -> Sequence[SubmittedOrder]:
        return []

    async def confirmed_open(self) -> Sequence[DiscrepancyRow]:
        return []


class OpenPositionsBody(BaseModel):
    positions: list[UUID]
    orders: list[UUID]


@router.get("/open", response_model=OpenPositionsBody)
async def read_open_positions(state: OpenStateDep) -> OpenPositionsBody:
    placeholder = _NoFactsYet()
    answer = await ReadOpenPositions(state, placeholder, placeholder).read()
    return OpenPositionsBody(
        positions=[position.allocation_id for position in answer.positions],
        orders=[order.attempt_id for order in answer.orders],
    )

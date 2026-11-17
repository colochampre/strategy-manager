"""``GET /api/safety-events``: the signed-in user's safety events (subscriber-safety SS.10).

One route, no parameter. It answers for the signed-in user ALONE, an admin included: the
user id comes from ``current_user`` and is the reader's argument, so no query string can
ask for another user's events. Newest first, at most 100. It writes nothing and needs no
credential.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.safety.application.read_safety_events import (
    ReadSafetyEvents,
    SafetyEventView,
)
from strategy_manager.safety.infrastructure.repository import SqlAlchemySafetyEventReader
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.wire import Instant

router = APIRouter(
    prefix="/safety-events",
    tags=["safety-events"],
    dependencies=[Depends(current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_read_safety_events(session: SessionDep) -> ReadSafetyEvents:
    return ReadSafetyEvents(SqlAlchemySafetyEventReader(session))


ReaderDep = Annotated[ReadSafetyEvents, Depends(get_read_safety_events)]


class SafetyEventBody(BaseModel):
    id: UUID
    kind: str
    strategy_id: UUID
    strategy_name: str
    allocation_id: UUID | None
    exchange: str
    venue: str
    symbol: str
    occurred_at: Instant
    detail: dict[str, str]


class SafetyEventsBody(BaseModel):
    events: list[SafetyEventBody]


def _body(event: SafetyEventView) -> SafetyEventBody:
    return SafetyEventBody(
        id=event.id,
        kind=event.kind.value,
        strategy_id=event.strategy_id,
        strategy_name=event.strategy_name,
        allocation_id=event.allocation_id,
        exchange=event.exchange,
        venue=event.venue,
        symbol=event.symbol,
        occurred_at=event.occurred_at,
        detail=event.detail,
    )


@router.get("", response_model=SafetyEventsBody)
async def read_safety_events(
    reader: ReaderDep, user: Annotated[User, Depends(current_user)]
) -> SafetyEventsBody:
    return SafetyEventsBody(events=[_body(e) for e in await reader.read(user.id)])

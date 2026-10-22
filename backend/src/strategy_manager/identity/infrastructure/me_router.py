"""``GET /me``: who is signed in (multi-user design AD1 and AD11).

The one ``/api`` route any signed-in user may call while the data is not yet
scoped by user (PR A): every other router requires the admin. The panel calls it
first on every load, so this is where a new user's row is created (decision 2:
anyone Access lets in becomes a user, with no approval).

A GET that writes, on purpose: the write is the user's own row, idempotent, and
at most once a minute after the first (``ResolveUser``).

``dry_run`` is ``.env``'s brake (decision 7), the value ``/health`` already
publishes. The user's own mode arrives with PR E.

The answer names a person, so it is never cached (``NoStoreMiddleware`` in
``main.create_app``).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.application.resolve_user import ResolveUser
from strategy_manager.identity.domain.user import InvalidEmailError
from strategy_manager.identity.infrastructure.dependencies import (
    UNAUTHORIZED_DETAIL,
    is_admin,
    verified_email,
)
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.clock import SystemClock

router = APIRouter(prefix="/me", tags=["identity"])


class MeBody(BaseModel):
    email: str
    is_admin: bool
    dry_run: bool


@router.get("", response_model=MeBody)
async def me(
    email: Annotated[str, Depends(verified_email)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeBody:
    try:
        user = await ResolveUser(SqlAlchemyUserRepository(session), SystemClock()).execute(email)
    except InvalidEmailError:
        # Access vouched for something that is not an address. It cannot become
        # a user, and the caller learns nothing more than from a forged token.
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL) from None
    await session.commit()
    return MeBody(
        email=user.email, is_admin=is_admin(user.email, settings), dry_run=settings.dry_run
    )

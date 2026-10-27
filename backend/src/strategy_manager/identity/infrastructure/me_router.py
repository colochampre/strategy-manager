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

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user, is_admin
from strategy_manager.shared.config import Settings, get_settings

router = APIRouter(prefix="/me", tags=["identity"])


class MeBody(BaseModel):
    email: str
    is_admin: bool
    dry_run: bool


@router.get("", response_model=MeBody)
async def me(
    user: Annotated[User, Depends(current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MeBody:
    return MeBody(
        email=user.email, is_admin=is_admin(user.email, settings), dry_run=settings.dry_run
    )

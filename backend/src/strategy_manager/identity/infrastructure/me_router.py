"""``/me``: who is signed in, and their mode (multi-user design AD1, AD7, AD11).

The panel calls ``GET /me`` first on every load, so this is where a new user's
row is created (decision 2: anyone Access lets in becomes a user, with no
approval). A GET that writes, on purpose: the write is the user's own row,
idempotent, and at most once a minute after the first (``ResolveUser``).

``mode`` is the user's own, as stored. ``dry_run_brake`` is ``.env``'s brake over
everyone (decision 7), the value ``/health`` already publishes. Both go out
unmerged: the panel says "forced by the brake" from the two together, which an
effective mode alone could not.

``POST /me/mode`` changes the signed-in user's mode and nobody else's: the route
takes no user id. Its rules are ``ChangeMode``'s. ``PUT /me/display-name`` is the
same for their name, under ``ChooseDisplayName``'s rules.

The answers name a person, so they are never cached (``NoStoreMiddleware`` in
``main.create_app``).
"""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.infrastructure.trade_capability_adapter import (
    VaultTradeCapabilityAdapter,
)
from strategy_manager.execution.infrastructure.live_exposure import SqlAlchemyLiveExposure
from strategy_manager.identity.application.change_mode import (
    ChangeMode,
    ModeChangeRefusedError,
    ModeRefusal,
)
from strategy_manager.identity.application.choose_display_name import ChooseDisplayName
from strategy_manager.identity.application.ports import DisplayNameTakenError
from strategy_manager.identity.domain.display_name import InvalidDisplayNameError
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user, is_admin
from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.mode import Mode

router = APIRouter(prefix="/me", tags=["identity"])

CurrentUserDep = Annotated[User, Depends(current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_MESSAGES = {
    ModeRefusal.BRAKE_ON: "The brake is on: everyone is in simulation until it is released.",
    ModeRefusal.LIVE_NEEDS_TRADE_KEY: "Going live needs an active key that can trade.",
    ModeRefusal.SIMULATION_NEEDS_FLAT: "Going to simulation needs nothing real held.",
}


class MeBody(BaseModel):
    email: str
    is_admin: bool
    mode: Mode
    dry_run_brake: bool
    display_name: str | None

    @classmethod
    def of(cls, user: User, settings: Settings) -> "MeBody":
        return cls(
            email=user.email,
            is_admin=is_admin(user.email, settings),
            mode=user.mode,
            dry_run_brake=settings.dry_run,
            display_name=user.display_name,
        )


class ChangeModeBody(BaseModel):
    mode: Mode


class DisplayNameBody(BaseModel):
    display_name: str


@router.get("", response_model=MeBody)
async def me(user: CurrentUserDep, settings: SettingsDep) -> MeBody:
    return MeBody.of(user, settings)


@router.post("/mode", response_model=MeBody)
async def change_mode(
    body: ChangeModeBody,
    user: CurrentUserDep,
    settings: SettingsDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeBody:
    use_case = ChangeMode(
        SqlAlchemyUserRepository(session),
        VaultTradeCapabilityAdapter(session),
        SqlAlchemyLiveExposure(session),
        session,
        brake=settings.dry_run,
    )
    try:
        await use_case.execute(user.id, body.mode)
    except ModeChangeRefusedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": exc.refusal.value,
                "message": _MESSAGES[exc.refusal],
                "symbols": list(exc.symbols),
            },
        ) from exc
    return MeBody.of(replace(user, mode=body.mode), settings)


@router.put("/display-name", response_model=MeBody)
async def choose_display_name(
    body: DisplayNameBody,
    user: CurrentUserDep,
    settings: SettingsDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeBody:
    use_case = ChooseDisplayName(SqlAlchemyUserRepository(session), session)
    try:
        name = await use_case.execute(user.id, body.display_name)
    except InvalidDisplayNameError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "DISPLAY_NAME_INVALID", "message": str(exc)}
        ) from exc
    except DisplayNameTakenError as exc:
        # Nothing of who holds it: their account is theirs to reveal.
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "DISPLAY_NAME_TAKEN", "message": "That name is taken."},
        ) from exc
    return MeBody.of(replace(user, display_name=name), settings)

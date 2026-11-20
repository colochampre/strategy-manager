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
same for their name, under ``ChooseDisplayName``'s rules. ``PUT /me/profile`` is
the sign-up form and ``POST /me/acceptance`` the box asked again on new versions,
under ``sign_up``'s rules (public-site LS2, LS6); ``GET /me`` says which of the two
the panel must show and publishes the versions in force. ``DELETE /me`` deletes
their own account, under ``DeleteAccount``'s (account-deletion S2-S5). After it,
the same e-mail signing in again is a new, empty user: the panel must not call
``GET /me`` once the account is gone, or it would create that user at once.

The answers name a person, so they are never cached (``NoStoreMiddleware`` in
``main.create_app``).
"""

import logging
from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import DBAPIError
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
from strategy_manager.identity.application.delete_account import (
    AccountChanged,
    AccountDeletionRefused,
    DeleteAccount,
)
from strategy_manager.identity.application.ports import DisplayNameTakenError
from strategy_manager.identity.application.sign_up import (
    AcceptLegalTerms,
    CompleteProfile,
    CorrectName,
    DeclarationMissingError,
    LegalVersionChangedError,
    ProfileAlreadyGivenError,
    ProfileMissingError,
    SignUpForm,
)
from strategy_manager.identity.domain.display_name import InvalidDisplayNameError
from strategy_manager.identity.domain.legal import (
    CURRENT_VERSIONS,
    LegalVersions,
    ProfileStatus,
    profile_status,
)
from strategy_manager.identity.domain.profile import CountryNotServedError, InvalidProfileError
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.account_deletion import (
    SqlAlchemyAccountCredentials,
    SqlAlchemyAccountPools,
    SqlAlchemyAuthoredStrategies,
    SqlAlchemyOwnPositions,
    SqlAlchemyOwnSeats,
)
from strategy_manager.identity.infrastructure.dependencies import (
    PROFILE_INCOMPLETE,
    PROFILE_INCOMPLETE_MESSAGE,
    current_user,
    is_admin,
    require_complete_profile,
)
from strategy_manager.identity.infrastructure.user_repository import (
    SqlAlchemyLegalAcceptances,
    SqlAlchemyUserRepository,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter

router = APIRouter(prefix="/me", tags=["identity"])
logger = logging.getLogger(__name__)

# SQLSTATE ``deadlock_detected``: Postgres aborted this transaction to break a cycle.
DEADLOCK_DETECTED = "40P01"

CurrentUserDep = Annotated[User, Depends(current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_MESSAGES = {
    ModeRefusal.BRAKE_ON: "The brake is on: everyone is in simulation until it is released.",
    ModeRefusal.LIVE_NEEDS_TRADE_KEY: "Going live needs an active key that can trade.",
    ModeRefusal.SIMULATION_NEEDS_FLAT: "Going to simulation needs nothing real held.",
}


class ProfileBody(BaseModel):
    first_name: str
    last_name: str
    cuit: str
    country: str


class LegalVersionsBody(BaseModel):
    terms: str
    privacy: str

    @classmethod
    def of(cls, versions: LegalVersions) -> "LegalVersionsBody":
        return cls(terms=versions.terms, privacy=versions.privacy)


class MeBody(BaseModel):
    email: str
    is_admin: bool
    mode: Mode
    dry_run_brake: bool
    display_name: str | None
    #: The identity given at sign-up. Only its owner reads it here.
    profile: ProfileBody | None
    #: What the panel shows first: nothing, the whole form, or the box alone.
    profile_status: ProfileStatus
    #: The versions in force: what the form and the box accept.
    legal_versions: LegalVersionsBody

    @classmethod
    def of(cls, user: User, settings: Settings, accepted: LegalVersions | None) -> "MeBody":
        """``accepted`` is the user's latest acceptance, if any."""
        profile = user.profile
        return cls(
            email=user.email,
            is_admin=is_admin(user.email, settings),
            mode=user.mode,
            dry_run_brake=settings.dry_run,
            display_name=user.display_name,
            profile=None
            if profile is None
            else ProfileBody(
                first_name=profile.first_name,
                last_name=profile.last_name,
                cuit=profile.cuit,
                country=profile.country,
            ),
            profile_status=profile_status(profile, accepted),
            legal_versions=LegalVersionsBody.of(CURRENT_VERSIONS),
        )


async def _me(user: User, settings: Settings, session: AsyncSession) -> MeBody:
    return MeBody.of(user, settings, await SqlAlchemyLegalAcceptances(session).latest(user.id))


class ChangeModeBody(BaseModel):
    mode: Mode


class DisplayNameBody(BaseModel):
    display_name: str


class SignUpBody(BaseModel):
    first_name: str
    last_name: str
    cuit: str
    country: str
    adult: bool
    truthful: bool
    accepts: bool
    terms_version: str
    privacy_version: str


class NameBody(BaseModel):
    #: Refused, not ignored: a CUIT sent here and dropped would read as changed.
    model_config = ConfigDict(extra="forbid")

    first_name: str
    last_name: str


class AcceptanceBody(BaseModel):
    accepts: bool
    terms_version: str
    privacy_version: str


def _version_changed() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "LEGAL_VERSION_CHANGED",
            "message": "The terms or the privacy policy changed: read them again.",
            "legal_versions": LegalVersionsBody.of(CURRENT_VERSIONS).model_dump(),
        },
    )


def _declaration_missing(exc: DeclarationMissingError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": "DECLARATION_MISSING", "field": exc.field, "message": str(exc)},
    )


@router.get("", response_model=MeBody)
async def me(user: CurrentUserDep, settings: SettingsDep, session: SessionDep) -> MeBody:
    return await _me(user, settings, session)


@router.put("/profile", response_model=MeBody)
async def give_profile(
    body: SignUpBody, user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> MeBody:
    use_case = CompleteProfile(
        SqlAlchemyUserRepository(session),
        SqlAlchemyLegalAcceptances(session),
        session,
        SystemClock(),
    )
    try:
        profile = await use_case.execute(user.id, SignUpForm(**body.model_dump()))
    except CountryNotServedError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "COUNTRY_NOT_SERVED", "message": str(exc)}
        ) from exc
    except InvalidProfileError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "PROFILE_INVALID", "field": exc.field, "message": str(exc)},
        ) from exc
    except DeclarationMissingError as exc:
        raise _declaration_missing(exc) from exc
    except LegalVersionChangedError as exc:
        raise _version_changed() from exc
    except ProfileAlreadyGivenError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "PROFILE_ALREADY_GIVEN",
                "message": "The profile was already given. Write to the contact address "
                "to correct it.",
            },
        ) from exc
    return await _me(replace(user, profile=profile), settings, session)


@router.post("/acceptance", response_model=MeBody)
async def accept_again(
    body: AcceptanceBody, user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> MeBody:
    use_case = AcceptLegalTerms(
        SqlAlchemyUserRepository(session),
        SqlAlchemyLegalAcceptances(session),
        session,
        SystemClock(),
    )
    try:
        await use_case.execute(
            user.id,
            accepts=body.accepts,
            terms_version=body.terms_version,
            privacy_version=body.privacy_version,
        )
    except DeclarationMissingError as exc:
        raise _declaration_missing(exc) from exc
    except LegalVersionChangedError as exc:
        raise _version_changed() from exc
    except ProfileMissingError as exc:
        raise _profile_incomplete() from exc
    return await _me(user, settings, session)


def _profile_incomplete() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": PROFILE_INCOMPLETE,
            "profile_status": ProfileStatus.MISSING.value,
            "message": PROFILE_INCOMPLETE_MESSAGE,
        },
    )


@router.put("/profile/name", response_model=MeBody)
async def correct_name(
    body: NameBody, user: CurrentUserDep, settings: SettingsDep, session: SessionDep
) -> MeBody:
    use_case = CorrectName(SqlAlchemyUserRepository(session), session)
    try:
        first, last = await use_case.execute(
            user.id, first_name=body.first_name, last_name=body.last_name
        )
    except InvalidProfileError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "PROFILE_INVALID", "field": exc.field, "message": str(exc)},
        ) from exc
    except ProfileMissingError as exc:
        raise _profile_incomplete() from exc
    profile = user.profile
    if profile is None:  # read before the UPDATE, which matched only a row with one
        raise _profile_incomplete()
    return await _me(
        replace(user, profile=replace(profile, first_name=first, last_name=last)), settings, session
    )


@router.delete("", status_code=204)
async def delete_account(
    user: CurrentUserDep,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    use_case = DeleteAccount(
        users=SqlAlchemyUserRepository(session),
        pools=SqlAlchemyAccountPools(session),
        authored=SqlAlchemyAuthoredStrategies(session, user.id),
        seats=SqlAlchemyOwnSeats(session),
        positions=SqlAlchemyOwnPositions(session),
        credentials=SqlAlchemyAccountCredentials(session),
        exposure=SqlAlchemyLiveExposure(session),
        pool_lock=PoolLockAdapter(session),
        commit=session,
        clock=SystemClock(),
    )
    try:
        await use_case.execute(user.id)
    except AccountDeletionRefused as exc:
        # Nothing was written, but the pool locks are still held: end the transaction.
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error": "ACCOUNT_HOLDS_POSITIONS",
                "message": "The account cannot be deleted while a position is open.",
                "symbols": list(exc.symbols),
                "strategies": [
                    {"id": str(held.id), "name": held.name, "symbols": list(held.symbols)}
                    for held in exc.strategies
                ],
            },
        ) from exc
    except AccountChanged as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "ACCOUNT_CHANGED", "message": str(exc)}
        ) from exc
    except DBAPIError as exc:
        # Postgres broke a deadlock by aborting the deletion, which wrote nothing: like
        # a change seen under the locks, it is worth trying again. Any other error
        # propagates.
        if getattr(getattr(exc.orig, "__cause__", None), "sqlstate", None) != DEADLOCK_DETECTED:
            raise
        await session.rollback()
        logger.warning("account deletion lost a deadlock: user=%s", user.id)
        raise HTTPException(
            status_code=409,
            detail={"error": "ACCOUNT_CHANGED", "message": "The deletion met another change."},
        ) from exc
    return Response(status_code=204)


@router.post("/mode", response_model=MeBody, dependencies=[Depends(require_complete_profile)])
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
    return await _me(replace(user, mode=body.mode), settings, session)


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
    return await _me(replace(user, display_name=name), settings, session)

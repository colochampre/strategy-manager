"""FastAPI dependencies: who is signed in, and whether they are the admin
(multi-user design AD1).

They replace the shared bearer token (``require_admin_token``). Its two rules
carry over unchanged:

- **Every refusal says the same word.** No assertion, a forged one, an expired
  one, one for another application: 401 ``unauthorized``, nothing more.
  Distinguishing them would help exactly the caller who should not be helped.
- **Authorisation is attached to the router**, never repeated per route, so a
  new route cannot be added without it.

Two answers are new. A signed-in user who is not the admin gets 403
``forbidden``: they proved who they are, and the answer may say so. And when the
identity cannot be checked at all, because Access's keys could not be fetched,
the answer is 503: a Cloudflare outage must never read as a forged token.

``require_admin`` returns nothing, for the old reason: there is nothing for the
endpoint to re-check, and a truthy return would invite it to. ``current_user``
returns the ``User``, because a scoped route needs its id (PR B).
"""

from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.application.ports import (
    IdentityRefusedError,
    IdentityUnavailableError,
    IdentityVerifierPort,
)
from strategy_manager.identity.application.resolve_user import ResolveUser
from strategy_manager.identity.domain.legal import ProfileStatus, profile_status
from strategy_manager.identity.domain.user import InvalidEmailError, User, normalize_email
from strategy_manager.identity.infrastructure.access_jwt import AccessJwtVerifier
from strategy_manager.identity.infrastructure.user_repository import (
    SqlAlchemyLegalAcceptances,
    SqlAlchemyUserRepository,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.clock import SystemClock

#: Where Access puts the assertion on every request it forwards to the origin.
ASSERTION_HEADER = "Cf-Access-Jwt-Assertion"

UNAUTHORIZED_DETAIL = "unauthorized"
FORBIDDEN_DETAIL = "forbidden"
UNAVAILABLE_DETAIL = "sign-in cannot be checked right now"


class DevIdentityVerifier:
    """Every request is ``DEV_USER_EMAIL``. For local runs without Cloudflare;
    ``assert_identity_configured`` refuses it beside Access and when live."""

    def __init__(self, email: str) -> None:
        self._email = email

    async def verify(self, assertion: str | None) -> str:
        return self._email


@lru_cache(maxsize=4)
def _access_verifier(team_domain: str, audience: str) -> AccessJwtVerifier:
    """One verifier per configuration for the process's life, so the cached
    keys survive between requests."""
    return AccessJwtVerifier(team_domain=team_domain, audience=audience, http=httpx.AsyncClient())


def identity_verifier_for(settings: Settings) -> IdentityVerifierPort:
    """Looked up by ``verified_email`` at call time, so tests replace it with
    ``tests.identity_auth.sign_in_as_admin``."""
    if settings.dev_user_email:
        return DevIdentityVerifier(settings.dev_user_email)
    return _access_verifier(settings.access_team_domain, settings.access_aud)


async def verified_email(
    settings: Annotated[Settings, Depends(get_settings)],
    assertion: Annotated[str | None, Header(alias=ASSERTION_HEADER)] = None,
) -> str:
    """The e-mail the request's assertion vouches for, as carried."""
    try:
        return await identity_verifier_for(settings).verify(assertion)
    except IdentityRefusedError:
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL) from None
    except IdentityUnavailableError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


def is_admin(email: str, settings: Settings) -> bool:
    """Both sides folded: ``ADMIN_EMAIL`` may be written in any case, and the
    identity provider may report any case."""
    try:
        return normalize_email(email) == normalize_email(settings.admin_email)
    except InvalidEmailError:
        return False


async def current_user(
    email: Annotated[str, Depends(verified_email)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """The signed-in ``User``: found, or created on the first request (decision
    2). Every scoped route filters by its ``id``.

    The row is committed here, before the route runs, so a route that later
    fails or rolls back never takes a new user's row down with it."""
    try:
        user = await ResolveUser(SqlAlchemyUserRepository(session), SystemClock()).execute(email)
    except InvalidEmailError:
        # Access vouched for something that is not an address. It cannot become
        # a user, and the caller learns nothing more than from a forged token.
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL) from None
    await session.commit()
    return user


PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"
PROFILE_INCOMPLETE_MESSAGE = "Complete the sign-up form first."
ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
ACCOUNT_SUSPENDED_MESSAGE = "This account is suspended."


async def profile_status_of(user: User, session: AsyncSession) -> ProfileStatus:
    """Whether ``user`` gave their profile and accepted the versions in force.
    Looked up by ``require_complete_profile`` at call time, so a router test about
    something else can waive the gate (``tests.identity_auth.waive_profile_gate``)."""
    accepted = await SqlAlchemyLegalAcceptances(session).latest(user.id)
    return profile_status(user.profile, accepted)


async def require_complete_profile(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """The sign-up gate, held on the server too (openspec/changes/public-site, LS4).

    Attached to every route that stores or trades for the user: saving a key, a
    subscription, a strategy, a mode change. Not to the ways out (reading, Close
    now, leaving a subscription, archiving or deleting a strategy, removing a key,
    deleting the account) nor to the way in (the form and the box). Changing a
    strategy runs ``require_complete_profile_unless_disabling`` instead, which lets
    a bare ``{"enabled": false}`` through: archiving needs a disabled strategy.
    ``test_every_api_route_is_guarded`` lists both sets, so a new route must be
    placed in one of them."""
    await ensure_complete_profile(user, session)


async def ensure_complete_profile(user: User, session: AsyncSession) -> None:
    """The gate's check and its 409, for a dependency that decides first whether
    the gate applies (``require_complete_profile_unless_disabling``).

    A suspended account meets the same gate (public-site LS9, PS.13 S5), whether
    or not it signed up, and is told of the suspension first: signing up would
    not open it."""
    if user.suspended:
        raise HTTPException(
            status_code=409,
            detail={"error": ACCOUNT_SUSPENDED, "message": ACCOUNT_SUSPENDED_MESSAGE},
        )
    status = await profile_status_of(user, session)
    if status is not ProfileStatus.COMPLETE:
        raise HTTPException(
            status_code=409,
            detail={
                "error": PROFILE_INCOMPLETE,
                "profile_status": status.value,
                "message": PROFILE_INCOMPLETE_MESSAGE,
            },
        )


async def require_admin(
    email: Annotated[str, Depends(verified_email)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not is_admin(email, settings):
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)

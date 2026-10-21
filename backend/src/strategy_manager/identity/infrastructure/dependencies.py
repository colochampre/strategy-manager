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
endpoint to re-check, and a truthy return would invite it to.
"""

from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, Header, HTTPException

from strategy_manager.identity.application.ports import (
    IdentityRefusedError,
    IdentityUnavailableError,
    IdentityVerifierPort,
)
from strategy_manager.identity.domain.user import InvalidEmailError, normalize_email
from strategy_manager.identity.infrastructure.access_jwt import AccessJwtVerifier
from strategy_manager.shared.config import Settings, get_settings

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


async def require_admin(
    email: Annotated[str, Depends(verified_email)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not is_admin(email, settings):
        raise HTTPException(status_code=403, detail=FORBIDDEN_DETAIL)

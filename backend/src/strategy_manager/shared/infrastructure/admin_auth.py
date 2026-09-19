"""Admin authentication: a bearer token, and nothing else.

Lives in ``shared`` rather than under any one module's ``infrastructure``,
because the token it checks is the deployment's one operator credential --
not a concept any single module owns. ``/strategies`` was its first consumer;
``/reconciliation`` is its second, and the second consumer is exactly what
proves this does not belong to the first.

A single bearer token rather than users, sessions or signatures, because
there is exactly one operator and the thing being protected is a handful of
configuration rows and a read-only operator view. What matters is that the
check is unconditional and structural -- see each router's own module for
where it is attached and why there.

**The reverse proxy is not the authorisation.** It was, until this module
existed -- a path allowlist in front of the application -- and that is a rule
living in a file this repository does not contain, enforced by a process this
repository does not start. The day someone widens it to serve a new route, an
admin surface silently comes back, and nothing in the application would
report that as a change. Keeping the proxy rule is right; depending on it is
not. This is the application's own copy of the judgement, and the one that
ships with the code that needs it.

**Every refusal says the same word.** Missing header, wrong scheme, wrong
token: one detail, one status. Distinguishing them would answer, for free,
"does this deployment have a token configured?" and "is my prefix right?",
which is reconnaissance handed to the only kind of caller who would ask.
"""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from strategy_manager.shared.config import Settings, get_settings

#: The one answer every failed authentication gets. See the module docstring:
#: a caller learning WHICH part of their credential was wrong is a caller
#: being helped to guess.
UNAUTHORIZED_DETAIL = "unauthorized"

#: RFC 7235 makes the scheme case-insensitive, so it is compared lowered.
BEARER_SCHEME = "bearer"


class AdminTokenAuth:
    """Authenticates an admin request by bearer token."""

    def __init__(self, expected_token: str) -> None:
        self._expected_token = expected_token

    @classmethod
    def from_settings(cls, settings: Settings) -> "AdminTokenAuth":
        return cls(expected_token=settings.admin_api_token)

    def authenticate(self, authorization: str | None) -> bool:
        if not self._expected_token:
            # An empty configured token would make comparison vacuous -- and
            # worse here than for the webhook, because the caller supplies the
            # other side: a request sending an empty token would MATCH, so an
            # unconfigured deployment would authenticate the internet.
            # Startup invariant 4 (``admin_token_invariant``, wired into
            # main.py's lifespan) refuses to start a deployment configured this
            # way; fail closed here regardless, because this class is also
            # constructed directly and must never authenticate on its own.
            return False
        if authorization is None:
            return False

        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != BEARER_SCHEME:
            return False
        # The token is compared byte for byte, with no stripping. Trimming it
        # would quietly accept a second, different string as the credential,
        # and a token is opaque bytes: nothing here can know that the space a
        # caller sent was not part of it.
        #
        # Constant-time. The margin an attacker could measure across a network
        # is small, but a variable-time comparison of a secret is not a thing
        # to knowingly leave in place.
        return hmac.compare_digest(
            token.encode("utf-8"), self._expected_token.encode("utf-8")
        )


async def require_admin_token(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency: raise 401 unless the request carries the token.

    Returns nothing on success on purpose. There is no identity to hand the
    endpoint -- the answer is only "this request may proceed" -- and a
    dependency that returned a truthy value would invite an endpoint to
    re-check it, which is how per-endpoint authorisation grows back.
    """

    if not AdminTokenAuth.from_settings(settings).authenticate(authorization):
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)

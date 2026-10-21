"""Verifies the Cloudflare Access assertion (multi-user design AD1).

Every request Access lets through reaches the origin carrying a signed JWT in
``Cf-Access-Jwt-Assertion``. The tunnel validates it already; the API checks it
again because it must not trust a header it cannot verify. A request that
reached the API port any other way would otherwise choose its own identity.

What is checked, per Cloudflare's page
(https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/,
read 2026-10-21):

- the RS256 signature, against the team's published keys, chosen by ``kid``;
- ``aud`` against this application's AUD tag;
- ``iss`` against the team domain;
- ``exp``, which must be present and in the future.

The e-mail claim is then the identity. That page's examples read
``payload.email`` without documenting it, so tasks.md A.13 confirms it on a
real token for each sign-in method.

**Only RS256 is accepted.** Anything else, HS256 above all, is refused before
the key is used, so the public key can never be used as an HMAC secret.

**The keys are cached and refreshed lazily.** A ``kid`` the cache does not hold
triggers one fetch, because Cloudflare rotates its keys. Refreshes happen at
most once a minute, so a made-up ``kid`` cannot make the API fetch on every
request.

**Nothing secret is logged.** Neither the assertion nor any claim reaches a
log: a refusal is answered 401 by the dependency and needs no line, and an
unavailable key set is logged once per failed fetch, without the response body.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt

from strategy_manager.identity.application.ports import (
    IdentityRefusedError,
    IdentityUnavailableError,
)

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"

#: The least time between two fetches of the key set.
REFRESH_INTERVAL_SECONDS = 60.0

#: A fetch of the key set gives up after this long. The request waiting on it is
#: a panel request, never the webhook (rule 3 does not depend on Access).
FETCH_TIMEOUT_SECONDS = 5.0


def team_issuer(team_domain: str) -> str:
    """``acme.cloudflareaccess.com``, ``https://acme.cloudflareaccess.com`` and
    either with a trailing slash all name one issuer."""
    domain = team_domain.strip().rstrip("/")
    if not domain.startswith("https://"):
        domain = f"https://{domain.removeprefix('http://')}"
    return domain


class AccessJwtVerifier:
    """Implements ``IdentityVerifierPort`` for Cloudflare Access."""

    def __init__(
        self,
        *,
        team_domain: str,
        audience: str,
        http: httpx.AsyncClient,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = team_issuer(team_domain)
        self._certs_url = f"{self._issuer}/cdn-cgi/access/certs"
        self._audience = audience
        self._http = http
        self._monotonic = monotonic
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._refresh = asyncio.Lock()

    async def verify(self, assertion: str | None) -> str:
        if not assertion:
            raise IdentityRefusedError

        try:
            header = jwt.get_unverified_header(assertion)
        except jwt.PyJWTError as error:
            raise IdentityRefusedError from error
        kid = header.get("kid")
        if header.get("alg") != ALGORITHM or not isinstance(kid, str) or not kid:
            raise IdentityRefusedError

        key = await self._key_for(kid)
        try:
            claims = jwt.decode(
                assertion,
                key=key,
                algorithms=[ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "aud", "iss"]},
            )
        except jwt.PyJWTError as error:
            raise IdentityRefusedError from error

        email = claims.get("email")
        if not isinstance(email, str) or not email:
            raise IdentityRefusedError
        return email

    async def _key_for(self, kid: str) -> Any:
        if kid in self._keys:
            return self._keys[kid]
        async with self._refresh:
            if kid not in self._keys and self._may_refresh():
                await self._fetch()
        try:
            return self._keys[kid]
        except KeyError:
            raise IdentityRefusedError from None

    def _may_refresh(self) -> bool:
        return (
            self._fetched_at is None
            or self._monotonic() - self._fetched_at >= REFRESH_INTERVAL_SECONDS
        )

    async def _fetch(self) -> None:
        # Stamped before the request, so that a failing endpoint is retried at
        # the same pace as an unknown ``kid``, not on every request.
        self._fetched_at = self._monotonic()
        try:
            response = await self._http.get(self._certs_url, timeout=FETCH_TIMEOUT_SECONDS)
            response.raise_for_status()
            key_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWTError) as error:
            logger.error(
                "Cloudflare Access signing keys could not be read from %s (%s); "
                "panel requests answer 503 until they can",
                self._certs_url,
                type(error).__name__,
            )
            if not self._keys:
                raise IdentityUnavailableError from error
            return
        self._keys = {jwk.key_id: jwk.key for jwk in key_set.keys if jwk.key_id}

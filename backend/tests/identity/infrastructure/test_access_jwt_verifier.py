"""``AccessJwtVerifier``: the API checks the Cloudflare Access assertion itself
(multi-user design AD1; tasks.md A.6).

The tunnel validates the token too, but the API must not trust a header it
cannot verify: a request that reached the API port any other way would choose
its own identity. Checked here, per Cloudflare's own page
(https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/):
the RS256 signature against the team's published keys, matched by ``kid``; the
audience; the issuer; the expiry. The e-mail is then the identity.

No network: the keys are served by an ``httpx.MockTransport`` and the tokens are
signed with RSA keys generated here.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from strategy_manager.identity.application.ports import (
    IdentityRefusedError,
    IdentityUnavailableError,
)
from strategy_manager.identity.infrastructure.access_jwt import AccessJwtVerifier

TEAM = "https://acme.cloudflareaccess.com"
CERTS = f"{TEAM}/cdn-cgi/access/certs"
AUD = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
EMAIL = "Owner@Example.com"


def _rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY_A = _rsa()
KEY_B = _rsa()


def _jwk(key: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    entry: dict[str, Any] = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {**entry, "kid": kid, "alg": "RS256", "use": "sig"}


def _token(
    key: rsa.RSAPrivateKey = KEY_A,
    kid: str = "kid-a",
    **overrides: Any,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "aud": [AUD],
        "iss": TEAM,
        "email": EMAIL,
        "iat": now,
        "exp": now + timedelta(hours=1),
        "sub": "user-id",
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


class _Keys:
    """Serves the certs endpoint and counts the fetches."""

    def __init__(self, *entries: dict[str, Any], status: int = 200) -> None:
        self.entries = list(entries)
        self.status = status
        self.fetches = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CERTS
        self.fetches += 1
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, json={"keys": self.entries})


class _Monotonic:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _verifier(
    keys: _Keys, monotonic: Callable[[], float] | None = None, team: str = TEAM
) -> AccessJwtVerifier:
    client = httpx.AsyncClient(transport=httpx.MockTransport(keys.handler))
    return AccessJwtVerifier(
        team_domain=team, audience=AUD, http=client, monotonic=monotonic or _Monotonic()
    )


async def test_a_valid_assertion_yields_its_email_as_carried() -> None:
    keys = _Keys(_jwk(KEY_A, "kid-a"))

    assert await _verifier(keys).verify(_token()) == EMAIL


async def test_a_bare_team_name_domain_is_accepted() -> None:
    """``ACCESS_TEAM_DOMAIN`` may be written without the scheme or with a
    trailing slash; both mean the same issuer."""
    keys = _Keys(_jwk(KEY_A, "kid-a"))

    assert await _verifier(keys, team="acme.cloudflareaccess.com/").verify(_token()) == EMAIL


@pytest.mark.parametrize("assertion", [None, ""])
async def test_no_assertion_is_refused_without_fetching_keys(assertion: str | None) -> None:
    keys = _Keys(_jwk(KEY_A, "kid-a"))

    with pytest.raises(IdentityRefusedError):
        await _verifier(keys).verify(assertion)

    assert keys.fetches == 0


_REFUSED = {
    "garbage": "not.a.jwt",
    "signed by another key under the same kid": _token(key=KEY_B),
    "another application's audience": _token(aud=["someone-else"]),
    "another team's issuer": _token(iss="https://evil.cloudflareaccess.com"),
    "expired": _token(exp=datetime.now(UTC) - timedelta(seconds=1)),
    "no expiry": _token(exp=None),
    "no email": _token(email=None),
    "an empty email": _token(email=""),
    "a non-string email": _token(email=["owner@example.com"]),
    "no kid": jwt.encode({"aud": [AUD], "iss": TEAM, "email": EMAIL}, KEY_A, "RS256"),
    "an HMAC token under a known kid": jwt.encode(
        {"aud": [AUD], "iss": TEAM, "email": EMAIL},
        "a-shared-secret-of-at-least-thirty-two-bytes",
        algorithm="HS256",
        headers={"kid": "kid-a"},
    ),
}


@pytest.mark.parametrize("label", list(_REFUSED))
async def test_an_assertion_that_does_not_hold_is_refused(label: str) -> None:
    token = _REFUSED[label]
    keys = _Keys(_jwk(KEY_A, "kid-a"))

    with pytest.raises(IdentityRefusedError):
        await _verifier(keys).verify(token)


async def test_the_keys_are_fetched_once_and_reused() -> None:
    keys = _Keys(_jwk(KEY_A, "kid-a"))
    verifier = _verifier(keys)

    for _ in range(3):
        await verifier.verify(_token())

    assert keys.fetches == 1


async def test_a_rotated_key_is_picked_up_by_one_refresh() -> None:
    """Cloudflare rotates its signing keys. A ``kid`` the cache does not hold
    triggers one refresh, after which the new key verifies."""
    keys = _Keys(_jwk(KEY_A, "kid-a"))
    clock = _Monotonic()
    verifier = _verifier(keys, clock)
    await verifier.verify(_token())

    keys.entries = [_jwk(KEY_A, "kid-a"), _jwk(KEY_B, "kid-b")]
    clock.now += 61

    assert await verifier.verify(_token(key=KEY_B, kid="kid-b")) == EMAIL
    assert keys.fetches == 2


async def test_unknown_kids_refresh_at_most_once_a_minute() -> None:
    """Otherwise anyone could make the API fetch Cloudflare's keys on every
    request by sending a made-up ``kid``."""
    keys = _Keys(_jwk(KEY_A, "kid-a"))
    clock = _Monotonic()
    verifier = _verifier(keys, clock)
    await verifier.verify(_token())

    for _ in range(3):
        with pytest.raises(IdentityRefusedError):
            await verifier.verify(_token(kid="made-up"))
        clock.now += 10

    assert keys.fetches == 1


async def test_a_kid_still_unknown_after_a_refresh_is_refused() -> None:
    keys = _Keys(_jwk(KEY_A, "kid-a"))

    with pytest.raises(IdentityRefusedError):
        await _verifier(keys).verify(_token(kid="made-up"))

    assert keys.fetches == 1


@pytest.mark.parametrize("status", [500, 404])
async def test_keys_that_cannot_be_fetched_make_identity_unavailable(status: int) -> None:
    """A Cloudflare outage is not the caller's fault: 503, never 401."""
    keys = _Keys(status=status)

    with pytest.raises(IdentityUnavailableError):
        await _verifier(keys).verify(_token())


async def test_a_network_failure_makes_identity_unavailable() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    verifier = AccessJwtVerifier(
        team_domain=TEAM,
        audience=AUD,
        http=httpx.AsyncClient(transport=httpx.MockTransport(unreachable)),
        monotonic=_Monotonic(),
    )

    with pytest.raises(IdentityUnavailableError):
        await verifier.verify(_token())


async def test_a_malformed_key_set_makes_identity_unavailable() -> None:
    def junk(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not": "a key set"})

    verifier = AccessJwtVerifier(
        team_domain=TEAM,
        audience=AUD,
        http=httpx.AsyncClient(transport=httpx.MockTransport(junk)),
        monotonic=_Monotonic(),
    )

    with pytest.raises(IdentityUnavailableError):
        await verifier.verify(_token())

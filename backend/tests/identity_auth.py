"""Signing a test request in (multi-user design AD1; tasks.md A.10).

The API verifies the Cloudflare Access assertion with ``AccessJwtVerifier``,
whose own tests cover the cryptography. Every other API test only needs SOME
assertion to stand for the admin and another to stand for a stranger, so it
replaces the verifier with ``StaticIdentityVerifier``: a table from assertion
to e-mail that refuses anything else, the way a forged token is refused.

Usage, in place of the old bearer token::

    @pytest.fixture(autouse=True)
    def _signed_in(monkeypatch):
        sign_in_as_admin(monkeypatch)

    await client.get("/api/pools", headers=ADMIN_HEADERS)
"""

import pytest

from strategy_manager.identity.application.ports import IdentityRefusedError
from strategy_manager.identity.infrastructure import dependencies
from strategy_manager.shared.config import Settings, get_settings

ADMIN_EMAIL = "owner@example.com"
ADMIN_ASSERTION = "assertion-for-the-admin"
OTHER_EMAIL = "someone@example.com"
OTHER_ASSERTION = "assertion-for-someone-else"

ADMIN_HEADERS = {dependencies.ASSERTION_HEADER: ADMIN_ASSERTION}
OTHER_HEADERS = {dependencies.ASSERTION_HEADER: OTHER_ASSERTION}
FORGED_HEADERS = {dependencies.ASSERTION_HEADER: "not-an-assertion-anyone-issued"}


class StaticIdentityVerifier:
    def __init__(self, emails: dict[str, str]) -> None:
        self._emails = emails

    async def verify(self, assertion: str | None) -> str:
        if assertion is None or assertion not in self._emails:
            raise IdentityRefusedError
        return self._emails[assertion]


def sign_in_as_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ADMIN_HEADERS`` sign in as the admin and ``OTHER_HEADERS`` as a user who
    is not; anything else is refused with 401."""
    monkeypatch.setattr(get_settings(), "admin_email", ADMIN_EMAIL)
    verifier = StaticIdentityVerifier(
        {ADMIN_ASSERTION: ADMIN_EMAIL, OTHER_ASSERTION: OTHER_EMAIL}
    )

    def verifier_for(settings: Settings) -> StaticIdentityVerifier:
        return verifier

    monkeypatch.setattr(dependencies, "identity_verifier_for", verifier_for)

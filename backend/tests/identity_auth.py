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

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from strategy_manager.identity.application.ports import IdentityRefusedError
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure import dependencies
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.domain.mode import Mode
from tests.owner import OWNER_ID

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


#: The signed-in user of an app served by ``without_a_database``. Not
#: ``OWNER_ID``: a route that wrote the fixtures' owner instead of the
#: signed-in user is told apart.
SIGNED_IN_ID = UUID("0a1b2c3d-0000-4000-8000-0000000051a0")


def without_a_database(app: FastAPI) -> FastAPI:
    """``current_user`` resolves the ``users`` row through the database. A test
    that serves a scoped route with no database answers the signed-in user
    here, as ``SIGNED_IN_ID``: still behind ``verified_email``, so a missing or
    forged assertion stays a 401."""

    async def _user(email: Annotated[str, Depends(dependencies.verified_email)]) -> User:
        now = datetime.now(UTC)
        return User(
            id=SIGNED_IN_ID, email=email, created_at=now, last_seen_at=now, mode=Mode.SIMULATION
        )

    app.dependency_overrides[dependencies.current_user] = _user
    return app


def act_as(app: FastAPI, user_id: UUID) -> FastAPI:
    """Make ``current_user`` resolve to ``user_id`` on an app that keeps its
    database and its real ``require_admin``. For a scoped route's test, whose
    fixtures own their rows as ``OWNER_ID`` (or as a second user) and need the
    signed-in user to be that owner without moving every seeded row."""

    async def _user(email: Annotated[str, Depends(dependencies.verified_email)]) -> User:
        now = datetime.now(UTC)
        return User(
            id=user_id, email=email, created_at=now, last_seen_at=now, mode=Mode.SIMULATION
        )

    app.dependency_overrides[dependencies.current_user] = _user
    return app


async def seed_admin(executor: AsyncConnection | AsyncSession) -> UUID:
    """The admin's ``users`` row, inserted unless it is already there; returns
    its id. Not committed. ``current_user`` resolves ``ADMIN_HEADERS`` to this
    very row, found by its e-mail, so a test can own rows as the signed-in admin
    before the first request."""
    await executor.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email) ON CONFLICT (email) DO NOTHING"),
        {"id": uuid4(), "email": ADMIN_EMAIL},
    )
    admin = (
        await executor.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": ADMIN_EMAIL}
        )
    ).scalar_one()
    return UUID(str(admin))


async def hand_owner_pools_to_admin(factory: async_sessionmaker[AsyncSession]) -> UUID:
    """Make the fixture's seeded pools the signed-in admin's, and return the
    admin's id. A scoped route answers only the signed-in user's pools
    (multi-user design AD8), and the fixtures seed them for ``OWNER_ID``, who is
    deliberately not the admin. Call it before any snapshot is written: a
    snapshot is bound to its pool's ``(id, user_id)``."""
    async with factory() as session:
        admin = await seed_admin(session)
        await session.execute(
            text("UPDATE capital_pools SET user_id = :admin WHERE user_id = :owner"),
            {"admin": admin, "owner": OWNER_ID},
        )
        await session.commit()
    return admin

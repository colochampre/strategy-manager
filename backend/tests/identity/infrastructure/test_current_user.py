"""``current_user``: the signed-in ``User``, row and id (multi-user design AD8;
tasks.md B.2).

Every scoped route filters by the id this dependency returns, so the id must be
the stored row's and one person must always receive the same one. The refusals
are ``verified_email``'s, and a refused request creates no row.

A route of its own on a bare FastAPI app, with a real PostgreSQL session.
"""

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure import dependencies
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import Settings
from tests.identity_auth import (
    FORGED_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    StaticIdentityVerifier,
    sign_in_as_admin,
)
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
        await session.commit()
    return pg_session_factory


@pytest.fixture
async def client(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    @app.get("/probe")
    async def probe(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
        return {"id": str(user.id), "email": user.email}

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


async def _stored(factory: async_sessionmaker[AsyncSession]) -> dict[str, UUID]:
    async with factory() as session:
        rows = await session.execute(text("SELECT email, id FROM users"))
        return {email: user_id for email, user_id in rows}


async def test_a_signed_in_request_receives_the_stored_user(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in_as_admin(monkeypatch)

    response = await client.get("/probe", headers=OTHER_HEADERS)

    assert response.status_code == 200
    stored = await _stored(factory)
    assert response.json() == {"id": str(stored[OTHER_EMAIL]), "email": OTHER_EMAIL}


async def test_one_person_always_receives_the_same_user(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in_as_admin(monkeypatch)

    first = await client.get("/probe", headers=OTHER_HEADERS)
    second = await client.get("/probe", headers=OTHER_HEADERS)

    assert first.json()["id"] == second.json()["id"]
    assert list(await _stored(factory)) == [OTHER_EMAIL]


@pytest.mark.parametrize("headers", [{}, FORGED_HEADERS], ids=["no assertion", "forged"])
async def test_a_refused_request_is_401_and_creates_no_user(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    sign_in_as_admin(monkeypatch)

    response = await client.get("/probe", headers=headers)

    assert (response.status_code, response.json()) == (401, {"detail": "unauthorized"})
    assert await _stored(factory) == {}


async def test_an_identity_that_is_not_an_address_is_401_and_creates_no_user(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = StaticIdentityVerifier({"odd": "not an address"})

    def verifier_for(settings: Settings) -> StaticIdentityVerifier:
        return verifier

    monkeypatch.setattr(dependencies, "identity_verifier_for", verifier_for)

    response = await client.get("/probe", headers={dependencies.ASSERTION_HEADER: "odd"})

    assert (response.status_code, response.json()) == (401, {"detail": "unauthorized"})
    assert await _stored(factory) == {}

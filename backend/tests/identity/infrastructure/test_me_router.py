"""``GET /api/me``: who is signed in (multi-user design AD1 and AD11; tasks.md
A.8).

The one route any signed-in user may call in PR A; every other ``/api`` route
is admin-only until PR B scopes the data. The panel calls it first on every
load, which is what creates a new user's row (decision 2: no approval).

Mounted through ``create_app()`` with a real PostgreSQL session.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.identity_auth import (
    ADMIN_EMAIL,
    ADMIN_HEADERS,
    FORGED_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    sign_in_as_admin,
)
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE users"))
        await session.commit()
    return pg_session_factory


@pytest.fixture
async def client(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


async def _emails(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with factory() as session:
        rows = await session.execute(text("SELECT email FROM users ORDER BY email"))
        return [email for (email,) in rows]


@pytest.mark.parametrize("dry_run", [True, False])
async def test_the_admin_is_told_who_they_are_and_the_brake(
    client: AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", dry_run)

    response = await client.get("/api/me", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"email": ADMIN_EMAIL, "is_admin": True, "dry_run": dry_run}
    assert await _emails(factory) == [ADMIN_EMAIL]


async def test_a_new_user_is_created_on_their_first_request_and_is_not_admin(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.get("/api/me", headers=OTHER_HEADERS)

    assert response.status_code == 200
    assert response.json()["email"] == OTHER_EMAIL
    assert response.json()["is_admin"] is False
    assert await _emails(factory) == [OTHER_EMAIL]


async def test_the_answer_is_never_cached(client: AsyncClient) -> None:
    """It names the signed-in person; a shared cache must not hand it to the
    next one."""
    response = await client.get("/api/me", headers=ADMIN_HEADERS)

    assert response.headers.get("cache-control") == "no-store"


async def test_a_second_request_creates_no_second_user(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.get("/api/me", headers=ADMIN_HEADERS)
    await client.get("/api/me", headers=ADMIN_HEADERS)

    assert await _emails(factory) == [ADMIN_EMAIL]


@pytest.mark.parametrize("headers", [{}, FORGED_HEADERS])
async def test_no_identity_is_401_and_creates_nobody(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], headers: dict[str, str]
) -> None:
    response = await client.get("/api/me", headers=headers)

    assert response.status_code == 401
    assert await _emails(factory) == []

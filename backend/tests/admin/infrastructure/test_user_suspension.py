"""``PUT /api/admin/users/{user_id}/suspension`` (public-site LS9, PS.13 S1), on
real PostgreSQL.

The admin suspends an account and lifts the suspension. The admin cannot suspend
themself, an unknown or deleted account is a 404, and anyone else is refused.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, OTHER_HEADERS, seed_admin, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import seed_user

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

USERS = "/api/admin/users"


def _suspension(user_id: UUID | str) -> str:
    return f"{USERS}/{user_id}/suspension"


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def admin(
    pg_session_factory: Factory,  # noqa: F811
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=ADMIN_HEADERS
    ) as client:
        yield client


async def _user(factory: Factory) -> tuple[UUID, str]:
    email = f"user-{uuid4().hex}@example.com"
    async with factory() as session:
        user_id = await seed_user(session, email)
        await session.commit()
    return user_id, email


async def _suspended_at(factory: Factory, user_id: UUID) -> Any:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT suspended_at FROM users WHERE id = :id"), {"id": user_id}
            )
        ).scalar_one()


async def _listed(admin: AsyncClient, email: str) -> dict[str, Any]:
    response = await admin.get(USERS)
    assert response.status_code == 200, response.text
    found = [each for each in response.json() if each["email"] == email]
    assert len(found) == 1, f"{email} is listed {len(found)} times"
    entry: dict[str, Any] = found[0]
    return entry


async def test_the_list_names_each_users_id_and_whether_they_are_suspended(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)

    entry = await _listed(admin, email)

    assert entry.get("id") == str(user_id)
    assert entry.get("suspended_at", "no suspension field") is None


async def test_the_admin_suspends_an_account_and_the_list_says_since_when(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)

    response = await admin.put(_suspension(user_id), json={"suspended": True})

    assert response.status_code == 204, response.text
    stored = await _suspended_at(pg_session_factory, user_id)
    assert stored is not None
    assert (await _listed(admin, email)).get("suspended_at") is not None


async def test_lifting_it_clears_the_date(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, email = await _user(pg_session_factory)
    await admin.put(_suspension(user_id), json={"suspended": True})

    response = await admin.put(_suspension(user_id), json={"suspended": False})

    assert response.status_code == 204, response.text
    assert await _suspended_at(pg_session_factory, user_id) is None
    assert (await _listed(admin, email)).get("suspended_at", "no suspension field") is None


async def test_suspending_twice_keeps_the_first_date(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, _ = await _user(pg_session_factory)
    await admin.put(_suspension(user_id), json={"suspended": True})
    first = await _suspended_at(pg_session_factory, user_id)

    response = await admin.put(_suspension(user_id), json={"suspended": True})

    assert response.status_code == 204, response.text
    assert await _suspended_at(pg_session_factory, user_id) == first


async def test_lifting_an_account_that_is_not_suspended_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, _ = await _user(pg_session_factory)

    response = await admin.put(_suspension(user_id), json={"suspended": False})

    assert response.status_code == 204, response.text
    assert await _suspended_at(pg_session_factory, user_id) is None


async def test_the_admin_cannot_suspend_themself(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    async with pg_session_factory() as session:
        admin_id = await seed_admin(session)
        await session.commit()

    response = await admin.put(_suspension(admin_id), json={"suspended": True})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {"error": "CANNOT_SUSPEND_YOURSELF"}
    assert await _suspended_at(pg_session_factory, admin_id) is None


async def test_an_unknown_account_is_a_404(admin: AsyncClient) -> None:
    response = await admin.put(_suspension(uuid4()), json={"suspended": True})

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {"error": "USER_NOT_FOUND"}


async def test_a_deleted_account_is_a_404_and_stays_as_it_was(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, _ = await _user(pg_session_factory)
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE users SET email = 'deleted-' || id::text || '@invalid', "
                "display_name = NULL, deleted_at = now() WHERE id = :id"
            ),
            {"id": user_id},
        )
        await session.commit()

    response = await admin.put(_suspension(user_id), json={"suspended": True})

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {"error": "USER_NOT_FOUND"}
    assert await _suspended_at(pg_session_factory, user_id) is None


async def test_another_user_is_refused_and_nothing_changes(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
) -> None:
    user_id, _ = await _user(pg_session_factory)

    response = await admin.put(
        _suspension(user_id), json={"suspended": True}, headers=OTHER_HEADERS
    )

    assert response.status_code == 403, response.text
    assert await _suspended_at(pg_session_factory, user_id) is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"suspended": "true"},
        {"suspended": 1},
        {"suspended": None},
        {"suspended": True, "reason": "spam"},
    ],
)
async def test_a_body_other_than_a_bare_boolean_is_a_422_and_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    admin: AsyncClient,
    body: dict[str, Any],
) -> None:
    user_id, _ = await _user(pg_session_factory)

    response = await admin.put(_suspension(user_id), json=body)

    assert response.status_code == 422, response.text
    assert await _suspended_at(pg_session_factory, user_id) is None

"""``PUT /api/me/display-name``: a user chooses the name others know them by
(multi-user decisions 17, 23 and 27; tasks.md F.1).

Mounted through ``create_app()`` with a real PostgreSQL session, because what
refuses a taken name is the index.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import (
    ADMIN_EMAIL,
    ADMIN_HEADERS,
    FORGED_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    sign_in_as_admin,
)
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401
from tests.owner import seed_user

pytestmark = pytest.mark.integration

ROUTE = "/api/me/display-name"


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
        await seed_user(session, ADMIN_EMAIL)
        await seed_user(session, OTHER_EMAIL)
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


async def _stored(factory: async_sessionmaker[AsyncSession], email: str) -> str | None:
    async with factory() as session:
        return (
            await session.execute(
                text("SELECT display_name FROM users WHERE email = :email"), {"email": email}
            )
        ).scalar_one()


async def _choose(client: AsyncClient, headers: dict[str, str], name: str) -> object:
    return await client.put(ROUTE, headers=headers, json={"display_name": name})


async def test_a_user_with_no_name_reads_none(client: AsyncClient) -> None:
    response = await client.get("/api/me", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json()["display_name"] is None


async def test_choosing_a_name_stores_its_normal_spelling_and_me_reads_it(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": "  Ana  P  "})

    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Ana P"
    assert response.json()["email"] == ADMIN_EMAIL
    assert await _stored(factory, ADMIN_EMAIL) == "Ana P"
    me = await client.get("/api/me", headers=ADMIN_HEADERS)
    assert me.json()["display_name"] == "Ana P"


async def test_a_name_changes_and_only_the_signed_in_users(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await _choose(client, OTHER_HEADERS, "Beto")
    await _choose(client, ADMIN_HEADERS, "Ana")

    response = await client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": "Carla"})

    assert response.status_code == 200
    assert await _stored(factory, ADMIN_EMAIL) == "Carla"
    assert await _stored(factory, OTHER_EMAIL) == "Beto"


async def test_a_name_someone_holds_is_a_409_ignoring_case_and_names_nobody(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await _choose(client, OTHER_HEADERS, "Ana")
    await _choose(client, ADMIN_HEADERS, "Carla")

    response = await client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": "ANA"})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "DISPLAY_NAME_TAKEN"
    assert OTHER_EMAIL not in response.text
    assert await _stored(factory, ADMIN_EMAIL) == "Carla"


async def test_a_user_can_change_the_case_of_their_own_name(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await _choose(client, ADMIN_HEADERS, "ana")

    response = await client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": "Ana"})

    assert response.status_code == 200, response.text
    assert await _stored(factory, ADMIN_EMAIL) == "Ana"


@pytest.mark.parametrize("name", ["", "   ", "An", "a" * 31, "ana@example.com", "A​na"])
async def test_an_invalid_name_is_a_422_and_a_name_cannot_be_emptied(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], name: str
) -> None:
    await _choose(client, ADMIN_HEADERS, "Ana")

    response = await client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": name})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "DISPLAY_NAME_INVALID"
    assert await _stored(factory, ADMIN_EMAIL) == "Ana"


@pytest.mark.parametrize(
    "spoof",
    [
        "Ana Lopez️",
        "Ana͏ Lopez",
        "ㅤㅤㅤ",
        "Ana Lopez\U000133fc",
        "Аna Lopez",
        "Ana Lоpez",
    ],
    ids=ascii,
)
async def test_an_invisible_character_cannot_pass_as_another_author(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], spoof: str
) -> None:
    await _choose(client, OTHER_HEADERS, "Ana Lopez")

    response = await client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": spoof})

    assert response.status_code == 422, ascii(response.text)
    assert response.json()["detail"]["error"] == "DISPLAY_NAME_INVALID"
    assert await _stored(factory, ADMIN_EMAIL) is None


async def test_two_users_racing_for_one_name_leave_one_holder(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    first, second = await asyncio.gather(
        client.put(ROUTE, headers=ADMIN_HEADERS, json={"display_name": "Ana"}),
        client.put(ROUTE, headers=OTHER_HEADERS, json={"display_name": "ana"}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    names = [await _stored(factory, ADMIN_EMAIL), await _stored(factory, OTHER_EMAIL)]
    assert sorted(name is None for name in names) == [False, True]


async def test_a_forged_assertion_changes_nothing(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.put(ROUTE, headers=FORGED_HEADERS, json={"display_name": "Ana"})

    assert response.status_code == 401
    assert await _stored(factory, ADMIN_EMAIL) is None

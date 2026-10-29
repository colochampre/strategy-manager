"""Authoring for any signed-in user, scoped to its author (multi-user design AD8,
decision 23; tasks.md D.4).

The strategies router and the pair catalogue answer every signed-in user, the admin
included, and only about that user's own strategies. Another user's strategy is a
strategy that does not exist: the SAME 404 on every route that names one. A name is
unique within one author, so two authors may share one and a repeat is a 409 that
says nothing of anybody else's strategies.

Mirrors ``test_router.py``: a bare app with the two routers mounted, the REAL
``current_user`` (so the signed-in user is resolved from the assertion's e-mail, as
in production) and a real PostgreSQL session. ``ADMIN_HEADERS`` sign in as the admin
and ``OTHER_HEADERS`` as a user who is not.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.strategies.application.register_strategy import RegisterStrategy
from strategy_manager.strategies.application.update_strategy import UpdateStrategy
from strategy_manager.strategies.infrastructure.pair_catalog_router import (
    get_pair_catalog,
)
from strategy_manager.strategies.infrastructure.pair_catalog_router import (
    router as pools_router,
)
from strategy_manager.strategies.infrastructure.router import router as strategies_router
from tests.identity_auth import (
    ADMIN_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    seed_admin,
    sign_in_as_admin,
)

pytestmark = pytest.mark.integration

MARKET = ("pionex", "spot", "USDT")


class _Catalog:
    async def available_pairs(self, pool: tuple[str, str, str]) -> frozenset[str]:
        return frozenset({"ETHUSDT", "SOLUSDT"})


@dataclass(frozen=True)
class World:
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    admin_id: UUID
    other_id: UUID


async def _seed_other(session: AsyncSession) -> UUID:
    """The non-admin's ``users`` row, found by the e-mail ``OTHER_HEADERS`` sign in as."""
    await session.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email) ON CONFLICT (email) DO NOTHING"),
        {"id": uuid4(), "email": OTHER_EMAIL},
    )
    found = (
        await session.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": OTHER_EMAIL}
        )
    ).scalar_one()
    return UUID(str(found))


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def world(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[World]:
    """Two signed-in users, each with a pool on ``MARKET``: the admin and a user
    who is not."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE strategy_enablement_events"))
        admin_id = await seed_admin(session)
        other_id = await _seed_other(session)
        for user_id in (admin_id, other_id):
            await session.execute(
                text(
                    "INSERT INTO capital_pools "
                    "(user_id, exchange, venue, settlement_currency, min_order_size) "
                    "VALUES (:user_id, :exchange, :venue, :currency, 10)"
                ),
                {
                    "user_id": user_id,
                    "exchange": MARKET[0],
                    "venue": MARKET[1],
                    "currency": MARKET[2],
                },
            )
        await session.commit()

    app = FastAPI()
    app.include_router(strategies_router)
    app.include_router(pools_router)
    app.dependency_overrides[get_pair_catalog] = _Catalog

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield World(api, pg_session_factory, admin_id, other_id)


async def _create(
    world: World,
    headers: dict[str, str],
    *,
    name: str | None = None,
    strategy_id: UUID | None = None,
) -> UUID:
    strategy_id = strategy_id or uuid4()
    response = await _post_create(world, headers, name=name, strategy_id=strategy_id)
    assert response.status_code == 201, response.text
    return strategy_id


async def _post_create(
    world: World,
    headers: dict[str, str],
    *,
    name: str | None = None,
    strategy_id: UUID | None = None,
    visibility: str | None = None,
) -> Response:
    strategy_id = strategy_id or uuid4()
    body: dict[str, Any] = {
        "id": str(strategy_id),
        "name": name or f"strategy-{strategy_id}",
        "exchange": MARKET[0],
        "venue": MARKET[1],
        "settlement_currency": MARKET[2],
        "fill_mode": "PARTIAL",
        "allowed_pairs": ["ETHUSDT"],
    }
    if visibility is not None:
        body["visibility"] = visibility
    return await world.client.post("/strategies", json=body, headers=headers)


async def _row(world: World, strategy_id: UUID) -> tuple[Any, ...] | None:
    """The strategy's whole stored row, to prove a refused write changed nothing."""
    async with world.factory() as session:
        row = (
            await session.execute(
                text("SELECT * FROM strategies WHERE id = :id"), {"id": strategy_id}
            )
        ).one_or_none()
    return None if row is None else tuple(row)


# --------------------------------------------------------------------------
# A user who is not the admin authors their own strategies
# --------------------------------------------------------------------------


async def test_a_non_admin_user_creates_a_strategy_and_is_its_author(world: World) -> None:
    response = await _post_create(world, OTHER_HEADERS)

    assert response.status_code == 201, response.text
    assert response.json()["webhook_secret"]
    async with world.factory() as session:
        author = (
            await session.execute(
                text("SELECT author_id FROM strategies WHERE id = :id"),
                {"id": response.json()["id"]},
            )
        ).scalar_one()
    assert UUID(str(author)) == world.other_id


async def test_a_non_admin_user_reads_their_own_strategy(world: World) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    detail = await world.client.get(f"/strategies/{strategy_id}", headers=OTHER_HEADERS)
    events = await world.client.get(f"/strategies/{strategy_id}/events", headers=OTHER_HEADERS)
    preview = await world.client.get(
        f"/strategies/{strategy_id}/share-preview", headers=OTHER_HEADERS
    )

    assert (detail.status_code, events.status_code, preview.status_code) == (200, 200, 200)
    assert detail.json()["id"] == str(strategy_id)


async def test_a_non_admin_user_updates_their_own_strategy(world: World) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    renamed = await world.client.patch(
        f"/strategies/{strategy_id}", json={"name": "renamed"}, headers=OTHER_HEADERS
    )
    pairs = await world.client.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["SOLUSDT"]},
        headers=OTHER_HEADERS,
    )

    assert (renamed.status_code, pairs.status_code) == (200, 200)
    assert renamed.json()["name"] == "renamed"
    assert pairs.json()["allowed_pairs"] == ["SOLUSDT"]


async def test_a_non_admin_user_archives_their_own_strategy(world: World) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    response = await world.client.post(f"/strategies/{strategy_id}/archive", headers=OTHER_HEADERS)

    assert response.status_code == 200, response.text
    assert response.json()["archived_at"] is not None


async def test_a_non_admin_user_deletes_their_own_strategy(world: World) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    response = await world.client.delete(f"/strategies/{strategy_id}", headers=OTHER_HEADERS)

    assert response.status_code == 204, response.text
    assert await _row(world, strategy_id) is None


async def test_a_non_admin_user_regenerates_their_own_webhook_secret(world: World) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    response = await world.client.post(
        f"/strategies/{strategy_id}/webhook-secret", headers=OTHER_HEADERS
    )

    assert response.status_code == 200, response.text
    assert response.json()["webhook_secret"]


async def test_a_non_admin_user_uses_the_pair_catalogue_for_their_pool(world: World) -> None:
    response = await world.client.get(
        "/pools/pionex/spot/USDT/available-pairs", headers=OTHER_HEADERS
    )

    assert response.status_code == 200, response.text
    assert response.json()["pairs"] == ["ETHUSDT", "SOLUSDT"]


async def test_a_non_admin_user_without_that_pool_gets_the_pool_404(world: World) -> None:
    """Scoped already (AD8): the catalogue is for the user's own pools."""
    async with world.factory() as session:
        await session.execute(
            text("DELETE FROM capital_pools WHERE user_id = :user_id"), {"user_id": world.other_id}
        )
        await session.commit()

    response = await world.client.get(
        "/pools/pionex/spot/USDT/available-pairs", headers=OTHER_HEADERS
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "no such pool"}


async def test_the_admin_authors_exactly_as_before(world: World) -> None:
    strategy_id = await _create(world, ADMIN_HEADERS)

    response = await world.client.get(f"/strategies/{strategy_id}", headers=ADMIN_HEADERS)

    assert response.status_code == 200


# --------------------------------------------------------------------------
# GET /strategies lists the user's own strategies only, the admin included
# --------------------------------------------------------------------------


async def test_the_list_holds_only_the_signed_in_users_own_strategies(world: World) -> None:
    mine = [await _create(world, OTHER_HEADERS) for _ in range(2)]
    theirs = await _create(world, ADMIN_HEADERS)

    other_list = await world.client.get("/strategies", headers=OTHER_HEADERS)
    admin_list = await world.client.get("/strategies", headers=ADMIN_HEADERS)

    assert {item["id"] for item in other_list.json()} == {str(item) for item in mine}
    assert [item["id"] for item in admin_list.json()] == [str(theirs)]


async def test_the_admin_does_not_see_a_non_admins_strategy_in_the_list_or_by_id(
    world: World,
) -> None:
    theirs = await _create(world, OTHER_HEADERS)

    listed = await world.client.get("/strategies?include_archived=true", headers=ADMIN_HEADERS)
    detail = await world.client.get(f"/strategies/{theirs}", headers=ADMIN_HEADERS)

    assert listed.json() == []
    assert detail.status_code == 404


# --------------------------------------------------------------------------
# Another user's strategy answers 404, the same as one that does not exist
# --------------------------------------------------------------------------

#: (id, method, path template, JSON body). One cross-user test per route.
ROUTES: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ("get", "GET", "/strategies/{id}", None),
    ("events", "GET", "/strategies/{id}/events", None),
    ("share-preview", "GET", "/strategies/{id}/share-preview", None),
    ("allowed-pairs", "PUT", "/strategies/{id}/allowed-pairs", {"pairs": ["SOLUSDT"]}),
    ("patch", "PATCH", "/strategies/{id}", {"name": "taken-over"}),
    ("archive", "POST", "/strategies/{id}/archive", None),
    ("delete", "DELETE", "/strategies/{id}", None),
    ("webhook-secret", "POST", "/strategies/{id}/webhook-secret", None),
]


@pytest.mark.parametrize(
    ("method", "template", "body"),
    [pytest.param(m, t, b, id=name) for name, m, t, b in ROUTES],
)
async def test_another_users_strategy_answers_the_404_of_a_strategy_that_does_not_exist(
    world: World, method: str, template: str, body: dict[str, Any] | None
) -> None:
    theirs = await _create(world, ADMIN_HEADERS)
    missing = uuid4()
    before = await _row(world, theirs)

    refused = await world.client.request(
        method, template.format(id=theirs), json=body, headers=OTHER_HEADERS
    )
    absent = await world.client.request(
        method, template.format(id=missing), json=body, headers=OTHER_HEADERS
    )

    assert (refused.status_code, absent.status_code) == (404, 404)
    assert refused.json() == json_with(absent.json(), swap=(str(missing), str(theirs)))
    assert await _row(world, theirs) == before  # nothing changed, nothing deleted


def json_with(body: Any, swap: tuple[str, str]) -> Any:
    """``body`` with ``swap[0]`` replaced by ``swap[1]`` in its detail text: the
    refusal names the id the caller sent, and nothing else may differ."""
    return {"detail": body["detail"].replace(*swap)}


# --------------------------------------------------------------------------
# A name is unique within one author
# --------------------------------------------------------------------------


async def test_two_authors_may_use_the_same_name(world: World) -> None:
    first = await _post_create(world, ADMIN_HEADERS, name="Alpha")
    second = await _post_create(world, OTHER_HEADERS, name="Alpha")

    assert (first.status_code, second.status_code) == (201, 201)


async def test_one_author_repeating_a_name_gets_a_409_that_names_nobody_else(
    world: World,
) -> None:
    await _create(world, ADMIN_HEADERS, name="Alpha")
    await _create(world, OTHER_HEADERS, name="Alpha")

    repeated = await _post_create(world, OTHER_HEADERS, name="Alpha")

    assert repeated.status_code == 409
    assert repeated.json() == {"detail": "a strategy named 'Alpha' already exists"}


async def test_renaming_to_a_name_the_author_already_uses_is_a_409(world: World) -> None:
    await _create(world, OTHER_HEADERS, name="Alpha")
    beta = await _create(world, OTHER_HEADERS, name="Beta")

    response = await world.client.patch(
        f"/strategies/{beta}", json={"name": "Alpha"}, headers=OTHER_HEADERS
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "a strategy named 'Alpha' already exists"}


async def test_renaming_to_a_name_only_another_author_uses_is_allowed(world: World) -> None:
    await _create(world, ADMIN_HEADERS, name="Alpha")
    mine = await _create(world, OTHER_HEADERS, name="Beta")

    response = await world.client.patch(
        f"/strategies/{mine}", json={"name": "Alpha"}, headers=OTHER_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Alpha"


async def test_an_id_another_user_holds_is_a_409_that_does_not_name_their_strategy(
    world: World,
) -> None:
    """The alert's id is global, so a clash is still a 409, but the refusal must not
    echo the name of a strategy its author never shared."""
    theirs = await _create(world, ADMIN_HEADERS, name="the-admins-private-name")

    response = await _post_create(world, OTHER_HEADERS, strategy_id=theirs)

    assert response.status_code == 409
    assert "the-admins-private-name" not in response.text


class _DriverError(Exception):
    def __init__(self, sqlstate: str, constraint_name: str | None) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    wrapper = Exception("dbapi wrapper")
    wrapper.__cause__ = _DriverError("23505", constraint_name)
    return IntegrityError("INSERT ...", {}, wrapper)


async def test_a_create_failing_on_another_constraint_is_not_reported_as_a_name_clash(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail(self: RegisterStrategy, command: object) -> object:
        raise _integrity_error("ux_something_else")

    monkeypatch.setattr(RegisterStrategy, "register", _fail)

    response = await _post_create(world, OTHER_HEADERS, name="Alpha")

    assert response.status_code == 500


async def test_an_update_failing_on_another_constraint_is_not_reported_as_a_name_clash(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    async def _fail(self: UpdateStrategy, command: object) -> object:
        raise _integrity_error(None)

    monkeypatch.setattr(UpdateStrategy, "update", _fail)

    response = await world.client.patch(
        f"/strategies/{strategy_id}", json={"name": "Alpha"}, headers=OTHER_HEADERS
    )

    assert response.status_code == 500


# --------------------------------------------------------------------------
# The admin setting no longer decides who may author
# --------------------------------------------------------------------------


async def test_an_unconfigured_admin_does_not_stop_a_signed_in_user_from_authoring(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "admin_email", "")

    created = await _post_create(world, OTHER_HEADERS)
    listed = await world.client.get("/strategies", headers=OTHER_HEADERS)

    assert created.status_code == 201
    assert len(listed.json()) == 1


# --------------------------------------------------------------------------
# The scoped repository
# --------------------------------------------------------------------------


async def test_the_scoped_repository_reads_only_its_authors_strategies(world: World) -> None:
    from strategy_manager.strategies.infrastructure.repository import AuthorStrategyRepository

    mine = await _create(world, OTHER_HEADERS)
    theirs = await _create(world, ADMIN_HEADERS)

    async with world.factory() as session:
        repository = AuthorStrategyRepository(session, world.other_id)
        found = await repository.get_by_id(mine)
        hidden = await repository.get_by_id(theirs)
        locked_found = await repository.get_by_id_for_update(mine)
        locked_hidden = await repository.get_by_id_for_update(theirs)
        listed = await repository.list_all(include_archived=True)

    assert found is not None and found.id == mine
    assert hidden is None
    assert locked_found is not None
    assert locked_hidden is None
    assert [item.id for item in listed] == [mine]


async def test_the_scoped_locked_read_waits_for_the_row_lock(world: World) -> None:
    """A write takes the scoped read inside the same row lock it took before: while
    another transaction holds the row, the scoped locked read waits."""
    from strategy_manager.strategies.infrastructure.repository import AuthorStrategyRepository

    mine = await _create(world, OTHER_HEADERS)

    async def _locked_read() -> object:
        async with world.factory() as session:
            return await AuthorStrategyRepository(session, world.other_id).get_by_id_for_update(
                mine
            )

    async with world.factory() as holder:
        await holder.execute(
            text("SELECT id FROM strategies WHERE id = :id FOR UPDATE"), {"id": mine}
        )
        task = asyncio.create_task(_locked_read())
        await asyncio.sleep(0.5)
        assert not task.done()
        await holder.rollback()

    assert await asyncio.wait_for(task, timeout=10) is not None

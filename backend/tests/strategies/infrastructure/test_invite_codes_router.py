"""The author's invitation codes (multi-user decision 41; tasks.md K.3).

``POST /strategies/{id}/invite-codes`` makes a code for a PRIVATE strategy and shows
it once; ``GET`` lists the live ones, with no code in them, only a hint and the
expiry; ``DELETE .../{code_id}`` revokes a live one. Each is the author's alone:
another user's strategy is the same 404 as one that does not exist. The code is
stored only as its SHA-256, and no log line names it.

Same bare app, real ``current_user`` and real PostgreSQL as
``test_strategy_authoring_scope.py``, whose world it reuses.
"""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from tests.identity_auth import ADMIN_HEADERS, OTHER_HEADERS
from tests.strategies.infrastructure.test_strategy_authoring_scope import (  # noqa: F401
    World,
    _create,
    _signed_in,
    world,
)
from tests.strategies.infrastructure.test_strategy_visibility import _name, _patch

pytestmark = pytest.mark.integration

LOGGER = "strategy_manager.strategies.application.invite_codes"
CODE_SHAPE = re.compile(r"[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}")


def _codes_of(strategy_id: UUID) -> str:
    return f"/strategies/{strategy_id}/invite-codes"


async def _private(world: World) -> UUID:  # noqa: F811
    """A PRIVATE strategy of the admin, who has a name."""
    await _name(world, world.admin_id)
    return await _create(world, ADMIN_HEADERS)


async def _issue(world: World, strategy_id: UUID, headers: dict[str, str] = ADMIN_HEADERS) -> Any:  # noqa: F811
    return await world.client.post(_codes_of(strategy_id), headers=headers)


async def _rows(world: World, strategy_id: UUID) -> list[dict[str, Any]]:  # noqa: F811
    async with world.factory() as session:
        found = await session.execute(
            text("SELECT * FROM invite_codes WHERE strategy_id = :id ORDER BY created_at, id"),
            {"id": strategy_id},
        )
        return [dict(row._mapping) for row in found]


async def _seed_code(
    world: World,  # noqa: F811
    strategy_id: UUID,
    *,
    created_at: datetime,
    hint: str = "ZZZZ",
    revoked: bool = False,
) -> UUID:
    code = uuid4()
    async with world.factory() as session:
        await session.execute(
            text(
                "INSERT INTO invite_codes (id, strategy_id, code_hash, hint, created_at, "
                "expires_at, revoked_at) VALUES (:id, :s, :h, :hint, :c, :e, :r)"
            ),
            {
                "id": code,
                "s": strategy_id,
                "h": hashlib.sha256(code.bytes).hexdigest(),
                "hint": hint,
                "c": created_at,
                "e": created_at + timedelta(days=7),
                "r": created_at if revoked else None,
            },
        )
        await session.commit()
    return code


async def _redeem(world: World, code: UUID, strategy_id: UUID) -> None:  # noqa: F811
    """Marks ``code`` used by the other user's seat, as K.4's subscribe will."""
    seat = uuid4()
    async with world.factory() as session:
        await session.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
                "SELECT :id, :u, :s, p.id, 10 FROM capital_pools p WHERE p.user_id = :u"
            ),
            {"id": seat, "u": world.other_id, "s": strategy_id},
        )
        await session.execute(
            text(
                "UPDATE invite_codes SET redeemed_by = :u, redeemed_at = now(), "
                "subscription_id = :seat WHERE id = :id"
            ),
            {"u": world.other_id, "seat": seat, "id": code},
        )
        await session.commit()


# --- issuing --------------------------------------------------------------------


async def test_a_code_is_shown_once_and_stored_only_as_its_hash(
    world: World,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await _private(world)
    before = datetime.now(UTC)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = await _issue(world, strategy_id)

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"id", "code", "hint", "expires_at"}
    assert CODE_SHAPE.fullmatch(body["code"])
    plain = body["code"].replace("-", "")
    [row] = await _rows(world, strategy_id)
    assert row["id"] == UUID(body["id"])
    assert row["code_hash"] == hashlib.sha256(plain.encode()).hexdigest()
    assert row["hint"] == plain[-4:] == body["hint"]
    assert before <= row["created_at"] <= datetime.now(UTC)
    assert row["expires_at"] - row["created_at"] == timedelta(days=7)
    assert datetime.fromisoformat(body["expires_at"]) == row["expires_at"]
    assert (row["revoked_at"], row["redeemed_by"], row["subscription_id"]) == (None, None, None)
    said = [each.getMessage() for each in caplog.records if each.name == LOGGER]
    assert len(said) == 1
    assert str(strategy_id) in said[0] and body["hint"] in said[0]
    # What is left once the ids and the hint are taken out names no half of the code.
    rest = said[0].replace(str(strategy_id), "").replace(body["id"], "").replace(body["hint"], "")
    assert plain[:4] not in rest


async def test_two_codes_differ(world: World) -> None:  # noqa: F811
    strategy_id = await _private(world)

    first, second = await _issue(world, strategy_id), await _issue(world, strategy_id)

    assert first.json()["code"] != second.json()["code"]
    assert len(await _rows(world, strategy_id)) == 2


@pytest.mark.parametrize("visibility", ["PUBLIC", "LINK"])
async def test_only_a_private_strategy_takes_codes(
    world: World,  # noqa: F811
    visibility: str,
) -> None:
    strategy_id = await _private(world)
    await _patch(world, strategy_id, {"visibility": visibility})

    response = await _issue(world, strategy_id)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRATEGY_NOT_PRIVATE"
    assert await _rows(world, strategy_id) == []


async def test_an_author_with_no_name_gets_no_code(world: World) -> None:  # noqa: F811
    """A code would open a page that names its author (decision 27)."""
    strategy_id = await _create(world, ADMIN_HEADERS)

    response = await _issue(world, strategy_id)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "AUTHOR_HAS_NO_DISPLAY_NAME"
    assert await _rows(world, strategy_id) == []


async def test_an_archived_strategy_gets_no_code(world: World) -> None:  # noqa: F811
    strategy_id = await _private(world)
    archived = await world.client.post(f"/strategies/{strategy_id}/archive", headers=ADMIN_HEADERS)
    assert archived.status_code == 200, archived.text

    response = await _issue(world, strategy_id)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRATEGY_ARCHIVED"
    assert await _rows(world, strategy_id) == []


# --- listing --------------------------------------------------------------------


async def test_the_list_holds_the_live_codes_oldest_first_and_never_a_code(
    world: World,  # noqa: F811
) -> None:
    strategy_id = await _private(world)
    now = datetime.now(UTC)
    older = await _seed_code(world, strategy_id, created_at=now - timedelta(days=2), hint="AAAA")
    newer = await _seed_code(world, strategy_id, created_at=now - timedelta(days=1), hint="BBBB")
    await _seed_code(world, strategy_id, created_at=now - timedelta(days=8), hint="CCCC")
    await _seed_code(world, strategy_id, created_at=now, hint="DDDD", revoked=True)
    used = await _seed_code(world, strategy_id, created_at=now, hint="EEEE")
    await _redeem(world, used, strategy_id)
    elsewhere = await _create(world, ADMIN_HEADERS)
    await _seed_code(world, elsewhere, created_at=now, hint="FFFF")

    response = await world.client.get(_codes_of(strategy_id), headers=ADMIN_HEADERS)

    assert response.status_code == 200, response.text
    listed = response.json()
    assert [(each["id"], each["hint"]) for each in listed] == [
        (str(older), "AAAA"),
        (str(newer), "BBBB"),
    ]
    assert all(set(each) == {"id", "hint", "expires_at"} for each in listed)


async def test_a_strategy_with_no_codes_lists_none(world: World) -> None:  # noqa: F811
    strategy_id = await _private(world)

    response = await world.client.get(_codes_of(strategy_id), headers=ADMIN_HEADERS)

    assert (response.status_code, response.json()) == (200, [])


# --- revoking -------------------------------------------------------------------


async def test_revoking_a_live_code_takes_it_off_the_list_and_keeps_the_row(
    world: World,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await _private(world)
    issued = (await _issue(world, strategy_id)).json()
    # Only the revoke's own lines: the issue above logs too when INFO is already on.
    caplog.clear()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = await world.client.delete(
            f"{_codes_of(strategy_id)}/{issued['id']}", headers=ADMIN_HEADERS
        )

    assert response.status_code == 204, response.text
    listed = await world.client.get(_codes_of(strategy_id), headers=ADMIN_HEADERS)
    assert listed.json() == []
    [row] = await _rows(world, strategy_id)
    assert row["revoked_at"] is not None
    said = [each.getMessage() for each in caplog.records if each.name == LOGGER]
    assert len(said) == 1
    assert issued["id"] in said[0] and issued["hint"] in said[0]


@pytest.mark.parametrize("state", ["revoked", "expired", "redeemed", "unknown", "other strategy"])
async def test_a_code_that_is_not_live_here_is_a_404_and_nothing_changes(
    world: World,  # noqa: F811
    state: str,
) -> None:
    strategy_id = await _private(world)
    now = datetime.now(UTC)
    if state == "other strategy":
        code = await _seed_code(world, await _create(world, ADMIN_HEADERS), created_at=now)
    elif state == "unknown":
        code = uuid4()
    else:
        created = now - timedelta(days=8) if state == "expired" else now
        code = await _seed_code(world, strategy_id, created_at=created, revoked=state == "revoked")
        if state == "redeemed":
            await _redeem(world, code, strategy_id)
    before = await _rows(world, strategy_id)

    response = await world.client.delete(f"{_codes_of(strategy_id)}/{code}", headers=ADMIN_HEADERS)

    assert response.status_code == 404
    assert await _rows(world, strategy_id) == before


# --- the author's alone ----------------------------------------------------------


async def test_another_users_strategy_is_a_404_on_every_route_and_nothing_changes(
    world: World,  # noqa: F811
) -> None:
    strategy_id = await _private(world)
    code = (await _issue(world, strategy_id)).json()["id"]
    before = await _rows(world, strategy_id)
    unknown = uuid4()

    answers = [
        await _issue(world, strategy_id, OTHER_HEADERS),
        await world.client.get(_codes_of(strategy_id), headers=OTHER_HEADERS),
        await world.client.delete(f"{_codes_of(strategy_id)}/{code}", headers=OTHER_HEADERS),
    ]
    unknowns = [
        await _issue(world, unknown, OTHER_HEADERS),
        await world.client.get(_codes_of(unknown), headers=OTHER_HEADERS),
        await world.client.delete(f"{_codes_of(unknown)}/{code}", headers=OTHER_HEADERS),
    ]

    assert [each.status_code for each in answers] == [404, 404, 404]
    assert [each.json() for each in answers] == [
        {"detail": each.json()["detail"].replace(str(unknown), str(strategy_id))}
        for each in unknowns
    ]
    assert await _rows(world, strategy_id) == before

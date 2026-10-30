"""A strategy is PRIVATE or PUBLIC, chosen by its author (decision 21; tasks.md D.5).

``POST /strategies`` takes ``visibility`` (default PRIVATE) and ``PATCH`` changes it,
for the author only: another user's strategy is the same 404 as one that does not
exist, from the author scoping of D.4. An archived strategy is read-only, visibility
included. Same bare app, real ``current_user`` and real PostgreSQL as
``test_strategy_authoring_scope.py``, whose world it reuses.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from tests.identity_auth import ADMIN_HEADERS, OTHER_HEADERS
from tests.strategies.infrastructure.test_strategy_authoring_scope import (  # noqa: F401
    World,
    _create,
    _post_create,
    _signed_in,
    world,
)

pytestmark = pytest.mark.integration


async def _stored_visibility(world: World, strategy_id: UUID) -> str:  # noqa: F811
    async with world.factory() as session:
        return str(
            (
                await session.execute(
                    text("SELECT visibility FROM strategies WHERE id = :id"), {"id": strategy_id}
                )
            ).scalar_one()
        )


async def _patch(
    world: World,  # noqa: F811
    strategy_id: UUID,
    body: dict[str, Any],
    headers: dict[str, str] = ADMIN_HEADERS,
) -> Any:
    return await world.client.patch(f"/strategies/{strategy_id}", json=body, headers=headers)


async def test_a_new_strategy_is_private_unless_the_author_says_otherwise(
    world: World,  # noqa: F811
) -> None:
    response = await _post_create(world, ADMIN_HEADERS)

    assert response.status_code == 201, response.text
    assert response.json()["visibility"] == "PRIVATE"
    assert await _stored_visibility(world, UUID(response.json()["id"])) == "PRIVATE"


async def test_a_strategy_is_created_public_when_the_author_asks(
    world: World,  # noqa: F811
) -> None:
    response = await _post_create(world, ADMIN_HEADERS, visibility="PUBLIC")

    assert response.status_code == 201, response.text
    assert response.json()["visibility"] == "PUBLIC"
    assert await _stored_visibility(world, UUID(response.json()["id"])) == "PUBLIC"


async def test_an_invalid_visibility_is_a_422_on_create_and_on_patch(
    world: World,  # noqa: F811
) -> None:
    created = await _post_create(world, ADMIN_HEADERS, visibility="SECRET")
    strategy_id = await _create(world, ADMIN_HEADERS)
    patched = await _patch(world, strategy_id, {"visibility": "SECRET"})

    assert (created.status_code, patched.status_code) == (422, 422)
    assert await _stored_visibility(world, strategy_id) == "PRIVATE"


async def test_the_author_changes_the_visibility_and_every_read_shows_it(
    world: World,  # noqa: F811
) -> None:
    strategy_id = await _create(world, OTHER_HEADERS)

    patched = await _patch(world, strategy_id, {"visibility": "PUBLIC"}, OTHER_HEADERS)
    detail = await world.client.get(f"/strategies/{strategy_id}", headers=OTHER_HEADERS)
    listing = await world.client.get("/strategies", headers=OTHER_HEADERS)
    back = await _patch(world, strategy_id, {"visibility": "PRIVATE"}, OTHER_HEADERS)

    assert patched.status_code == 200, patched.text
    assert patched.json()["visibility"] == "PUBLIC"
    assert detail.json()["visibility"] == "PUBLIC"
    assert [row["visibility"] for row in listing.json()] == ["PUBLIC"]
    assert back.json()["visibility"] == "PRIVATE"
    assert await _stored_visibility(world, strategy_id) == "PRIVATE"


async def test_a_patch_that_names_no_visibility_leaves_it_alone(
    world: World,  # noqa: F811
) -> None:
    created = await _post_create(world, ADMIN_HEADERS, visibility="PUBLIC")
    strategy_id = UUID(created.json()["id"])

    renamed = await _patch(world, strategy_id, {"name": "renamed"})

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["visibility"] == "PUBLIC"
    assert await _stored_visibility(world, strategy_id) == "PUBLIC"


async def test_another_users_visibility_patch_is_a_404_and_changes_nothing(
    world: World,  # noqa: F811
) -> None:
    strategy_id = await _create(world, ADMIN_HEADERS)

    response = await _patch(world, strategy_id, {"visibility": "PUBLIC"}, OTHER_HEADERS)

    assert response.status_code == 404
    assert await _stored_visibility(world, strategy_id) == "PRIVATE"


async def test_an_archived_strategys_visibility_cannot_change(
    world: World,  # noqa: F811
) -> None:
    strategy_id = await _create(world, ADMIN_HEADERS)
    archived = await world.client.post(f"/strategies/{strategy_id}/archive", headers=ADMIN_HEADERS)
    assert archived.status_code == 200, archived.text

    response = await _patch(world, strategy_id, {"visibility": "PUBLIC"})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRATEGY_ARCHIVED"
    assert await _stored_visibility(world, strategy_id) == "PRIVATE"

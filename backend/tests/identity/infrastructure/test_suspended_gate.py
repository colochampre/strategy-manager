"""A suspended account at the API (public-site LS9, PS.13 S5).

A suspended user's gated writes answer 409 ``ACCOUNT_SUSPENDED``, signed up or not;
the ways out stay open, and ``GET /api/me`` says so. Lifting the suspension opens
the gate again. Real PostgreSQL through ``create_app()``.
"""

import re
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.identity.infrastructure.test_every_api_route_is_guarded import (
    GATED_BUT_FOR_DISABLING,
    GATED_UNTIL_SIGNED_UP,
)
from tests.identity.infrastructure.test_me_profile_router import (  # noqa: F401
    FORM,
    PROFILE,
    STRATEGIES,
    _enabled,
    _own_enabled_strategy,
    _signed_in,
    client,
    factory,
)
from tests.identity_auth import ADMIN_EMAIL, ADMIN_HEADERS
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401

Factory = async_sessionmaker[AsyncSession]

SUSPENDED = {
    "error": "ACCOUNT_SUSPENDED",
    "message": "This account is suspended.",
}


async def _set_suspended(sessions: Factory, email: str, suspended: bool) -> None:
    async with sessions() as session:
        await session.execute(
            text(
                "UPDATE users SET suspended_at = CASE WHEN :s THEN now() END WHERE email = :e"
            ),
            {"s": suspended, "e": email},
        )
        await session.commit()


async def _answers(api: AsyncClient) -> dict[str, tuple[int, str]]:
    answers = {}
    for method, path in sorted(GATED_UNTIL_SIGNED_UP | GATED_BUT_FOR_DISABLING):
        concrete = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        response = await api.request(method, concrete, headers=ADMIN_HEADERS, json={})
        answers[f"{method} {path}"] = (response.status_code, response.text)
    return answers


async def test_every_gated_route_answers_409_to_a_suspended_user_until_it_is_lifted(
    client: AsyncClient,  # noqa: F811
    factory: Factory,  # noqa: F811
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)
    await _set_suspended(factory, ADMIN_EMAIL, True)

    for route, (status, body) in (await _answers(client)).items():
        assert status == 409, route
        assert '"ACCOUNT_SUSPENDED"' in body, route

    await _set_suspended(factory, ADMIN_EMAIL, False)

    for route, (_, body) in (await _answers(client)).items():
        assert "ACCOUNT_SUSPENDED" not in body, route


async def test_the_refusal_names_the_suspension(
    client: AsyncClient,  # noqa: F811
    factory: Factory,  # noqa: F811
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)
    await _set_suspended(factory, ADMIN_EMAIL, True)

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == SUSPENDED


async def test_a_suspended_user_who_has_not_signed_up_is_told_of_the_suspension(
    client: AsyncClient,  # noqa: F811
    factory: Factory,  # noqa: F811
) -> None:
    await _set_suspended(factory, ADMIN_EMAIL, True)

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "LIVE"})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == SUSPENDED


async def test_me_says_whether_the_account_is_suspended(
    client: AsyncClient,  # noqa: F811
    factory: Factory,  # noqa: F811
) -> None:
    before = (await client.get("/api/me", headers=ADMIN_HEADERS)).json()
    await _set_suspended(factory, ADMIN_EMAIL, True)
    during = (await client.get("/api/me", headers=ADMIN_HEADERS)).json()

    assert before.get("suspended") is False
    assert during.get("suspended") is True


async def test_a_suspended_author_can_still_disable_their_strategy(
    client: AsyncClient,  # noqa: F811
    factory: Factory,  # noqa: F811
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)
    strategy_id = await _own_enabled_strategy(factory, ADMIN_EMAIL)
    await _set_suspended(factory, ADMIN_EMAIL, True)

    response = await client.patch(
        f"{STRATEGIES}/{strategy_id}", headers=ADMIN_HEADERS, json={"enabled": False}
    )

    assert response.status_code == 200, response.text
    assert await _enabled(factory, strategy_id) is False


async def test_a_suspended_user_can_still_delete_the_account(
    client: AsyncClient,  # noqa: F811
    factory: Factory,  # noqa: F811
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)
    await _set_suspended(factory, ADMIN_EMAIL, True)

    response = await client.delete("/api/me", headers=ADMIN_HEADERS)

    assert response.status_code == 204, response.text

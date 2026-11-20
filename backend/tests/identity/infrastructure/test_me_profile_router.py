"""``PUT /api/me/profile``, ``POST /api/me/acceptance`` and what ``GET /api/me``
says of them (openspec/changes/public-site, LS2, LS3, LS6).

Mounted through ``create_app()`` with a real PostgreSQL session: the profile is
given once by one conditional UPDATE, and what is stored is read back from the
tables, not from the answer.
"""

import re
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.identity.domain.legal import CURRENT_VERSIONS
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity.infrastructure.test_every_api_route_is_guarded import (
    GATED_UNTIL_SIGNED_UP,
)
from tests.identity_auth import (
    ADMIN_EMAIL,
    ADMIN_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    sign_in_as_admin,
)
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401
from tests.owner import seed_user

pytestmark = pytest.mark.integration

PROFILE = "/api/me/profile"
ACCEPTANCE = "/api/me/acceptance"
FORM: dict[str, Any] = {
    "first_name": " Ana ",
    "last_name": "Pérez",
    "cuit": "20-12345678-6",
    "country": "AR",
    "adult": True,
    "truthful": True,
    "accepts": True,
    "terms_version": CURRENT_VERSIONS.terms,
    "privacy_version": CURRENT_VERSIONS.privacy,
}
VERSIONS = {"terms": CURRENT_VERSIONS.terms, "privacy": CURRENT_VERSIONS.privacy}


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


async def _profile_row(factory: async_sessionmaker[AsyncSession], email: str) -> tuple[Any, ...]:
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT first_name, last_name, cuit, country, "
                    "adult_declared_at IS NOT NULL, truthful_declared_at IS NOT NULL "
                    "FROM users WHERE email = :email"
                ),
                {"email": email},
            )
        ).one()
        return tuple(row)


async def _acceptances(
    factory: async_sessionmaker[AsyncSession], email: str
) -> list[tuple[str, str]]:
    async with factory() as session:
        rows = await session.execute(
            text(
                "SELECT a.terms_version, a.privacy_version FROM legal_acceptances a "
                "JOIN users u ON u.id = a.user_id WHERE u.email = :email ORDER BY a.accepted_at"
            ),
            {"email": email},
        )
        return [tuple(row) for row in rows]  # type: ignore[misc]


NOTHING = (None, None, None, None, False, False)


async def test_a_new_user_has_no_profile_and_reads_the_versions_in_force(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/me", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["profile"] is None
    assert body["profile_status"] == "MISSING"
    assert body["legal_versions"] == VERSIONS


async def test_the_form_stores_the_profile_and_one_acceptance(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile"] == {
        "first_name": "Ana",
        "last_name": "Pérez",
        "cuit": "20123456786",
        "country": "AR",
    }
    assert body["profile_status"] == "COMPLETE"
    assert await _profile_row(factory, ADMIN_EMAIL) == (
        "Ana",
        "Pérez",
        "20123456786",
        "AR",
        True,
        True,
    )
    assert await _acceptances(factory, ADMIN_EMAIL) == [
        (CURRENT_VERSIONS.terms, CURRENT_VERSIONS.privacy)
    ]
    me = (await client.get("/api/me", headers=ADMIN_HEADERS)).json()
    assert (me["profile"], me["profile_status"]) == (body["profile"], "COMPLETE")


async def test_one_users_profile_is_not_another_users(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)

    other = (await client.get("/api/me", headers=OTHER_HEADERS)).json()

    assert (other["profile"], other["profile_status"]) == (None, "MISSING")
    assert await _profile_row(factory, OTHER_EMAIL) == NOTHING


async def test_a_country_other_than_argentina_is_a_422_and_stores_nothing(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.put(PROFILE, headers=ADMIN_HEADERS, json={**FORM, "country": "UY"})

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "COUNTRY_NOT_SERVED",
        "message": "The service is offered only to residents of Argentina for now.",
    }
    assert await _profile_row(factory, ADMIN_EMAIL) == NOTHING
    assert await _acceptances(factory, ADMIN_EMAIL) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("cuit", "20-12345678-0"), ("first_name", "   "), ("last_name", "a" * 81)],
)
async def test_a_field_that_cannot_be_true_is_a_422_naming_it(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], field: str, value: str
) -> None:
    response = await client.put(PROFILE, headers=ADMIN_HEADERS, json={**FORM, field: value})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert (detail["error"], detail["field"]) == ("PROFILE_INVALID", field)
    assert await _profile_row(factory, ADMIN_EMAIL) == NOTHING


@pytest.mark.parametrize("box", ["adult", "truthful", "accepts"])
async def test_an_unticked_box_is_a_422_naming_it(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession], box: str
) -> None:
    response = await client.put(PROFILE, headers=ADMIN_HEADERS, json={**FORM, box: False})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert (detail["error"], detail["field"]) == ("DECLARATION_MISSING", box)
    assert await _profile_row(factory, ADMIN_EMAIL) == NOTHING
    assert await _acceptances(factory, ADMIN_EMAIL) == []


async def test_a_form_read_under_other_versions_is_a_409_naming_the_ones_in_force(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.put(
        PROFILE, headers=ADMIN_HEADERS, json={**FORM, "terms_version": "older"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "LEGAL_VERSION_CHANGED"
    assert response.json()["detail"]["legal_versions"] == VERSIONS
    assert await _profile_row(factory, ADMIN_EMAIL) == NOTHING


async def test_the_profile_is_given_once(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)

    response = await client.put(
        PROFILE, headers=ADMIN_HEADERS, json={**FORM, "first_name": "Beatriz"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "PROFILE_ALREADY_GIVEN"
    assert (await _profile_row(factory, ADMIN_EMAIL))[0] == "Ana"
    assert len(await _acceptances(factory, ADMIN_EMAIL)) == 1


async def test_the_box_alone_without_a_profile_is_a_409(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await client.post(
        ACCEPTANCE,
        headers=ADMIN_HEADERS,
        json={
            "accepts": True,
            "terms_version": VERSIONS["terms"],
            "privacy_version": VERSIONS["privacy"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "PROFILE_INCOMPLETE"
    assert await _acceptances(factory, ADMIN_EMAIL) == []


async def test_new_versions_ask_the_box_again_and_ticking_it_completes_the_profile(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)
    async with factory() as session:
        # An acceptance of older versions, recorded after the first one: the latest wins.
        await session.execute(
            text(
                "INSERT INTO legal_acceptances (id, user_id, terms_version, privacy_version, "
                "accepted_at) SELECT :id, a.user_id, 'older', 'older', "
                "max(a.accepted_at) + interval '1 microsecond' FROM legal_acceptances a "
                "JOIN users u ON u.id = a.user_id WHERE u.email = :email GROUP BY a.user_id"
            ),
            {"id": uuid4(), "email": ADMIN_EMAIL},
        )
        await session.commit()
    assert (await client.get("/api/me", headers=ADMIN_HEADERS)).json()[
        "profile_status"
    ] == "ACCEPTANCE_OUTDATED"

    unticked = await client.post(
        ACCEPTANCE,
        headers=ADMIN_HEADERS,
        json={
            "accepts": False,
            "terms_version": VERSIONS["terms"],
            "privacy_version": VERSIONS["privacy"],
        },
    )
    response = await client.post(
        ACCEPTANCE,
        headers=ADMIN_HEADERS,
        json={
            "accepts": True,
            "terms_version": VERSIONS["terms"],
            "privacy_version": VERSIONS["privacy"],
        },
    )

    assert unticked.status_code == 422
    assert unticked.json()["detail"] == {
        "error": "DECLARATION_MISSING",
        "field": "accepts",
        "message": "accepts must be ticked",
    }
    assert response.status_code == 200, response.text
    assert response.json()["profile_status"] == "COMPLETE"
    assert len(await _acceptances(factory, ADMIN_EMAIL)) == 3


async def test_the_box_read_under_other_versions_is_a_409(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)

    response = await client.post(
        ACCEPTANCE,
        headers=ADMIN_HEADERS,
        json={"accepts": True, "terms_version": VERSIONS["terms"], "privacy_version": "older"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "LEGAL_VERSION_CHANGED"
    assert len(await _acceptances(factory, ADMIN_EMAIL)) == 1


async def test_every_gated_route_answers_409_until_the_user_signs_up(client: AsyncClient) -> None:
    """LS4: the panel's form is not the only guard. The gate answers before the
    route reads its path or body, so an empty request is enough to meet it."""
    for method, path in sorted(GATED_UNTIL_SIGNED_UP):
        concrete = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        response = await client.request(method, concrete, headers=ADMIN_HEADERS, json={})

        assert response.status_code == 409, f"{method} {path}"
        assert response.json()["detail"] == {
            "error": "PROFILE_INCOMPLETE",
            "profile_status": "MISSING",
            "message": "Complete the sign-up form first.",
        }, f"{method} {path}"

    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)

    for method, path in sorted(GATED_UNTIL_SIGNED_UP):
        concrete = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        response = await client.request(method, concrete, headers=ADMIN_HEADERS, json={})

        assert "PROFILE_INCOMPLETE" not in response.text, f"{method} {path}"


async def test_new_versions_close_the_gate_until_the_box_is_ticked_again(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO legal_acceptances (id, user_id, terms_version, privacy_version, "
                "accepted_at) SELECT :id, a.user_id, 'older', 'older', "
                "max(a.accepted_at) + interval '1 microsecond' FROM legal_acceptances a "
                "JOIN users u ON u.id = a.user_id WHERE u.email = :email GROUP BY a.user_id"
            ),
            {"id": uuid4(), "email": ADMIN_EMAIL},
        )
        await session.commit()

    response = await client.post("/api/me/mode", headers=ADMIN_HEADERS, json={"mode": "SIMULATION"})

    assert response.status_code == 409
    assert response.json()["detail"]["profile_status"] == "ACCEPTANCE_OUTDATED"


async def test_the_ways_out_stay_open_to_a_user_who_has_not_signed_up(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """Deleting the account never meets the gate. The other ways out are pinned by
    the route walk (``test_every_api_route_is_guarded``), not exercised here."""
    response = await client.delete("/api/me", headers=ADMIN_HEADERS)

    assert response.status_code == 204, response.text
    async with factory() as session:
        deleted = (
            await session.execute(text("SELECT count(*) FROM users WHERE deleted_at IS NOT NULL"))
        ).scalar_one()
    assert deleted == 1


async def test_deleting_the_account_erases_the_identity_and_keeps_the_acceptances(
    client: AsyncClient, factory: async_sessionmaker[AsyncSession]
) -> None:
    """LS5, until LQ6 is answered: the identity goes with the e-mail and the name;
    the acceptance record stays, as the ledger does."""
    await client.put(PROFILE, headers=ADMIN_HEADERS, json=FORM)

    response = await client.delete("/api/me", headers=ADMIN_HEADERS)

    assert response.status_code == 204, response.text
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT u.first_name, u.last_name, u.cuit, u.country, u.adult_declared_at, "
                    "u.truthful_declared_at, count(a.id) FROM users u "
                    "LEFT JOIN legal_acceptances a ON a.user_id = u.id "
                    "WHERE u.deleted_at IS NOT NULL GROUP BY u.id"
                )
            )
        ).one()
    assert tuple(row) == (None, None, None, None, None, None, 1)

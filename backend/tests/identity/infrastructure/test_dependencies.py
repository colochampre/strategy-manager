"""``verified_email`` and ``require_admin`` (multi-user design AD1; tasks.md A.7).

Mounted on a minimal app so that what is proven is the dependency, not a router.
The verifier is real in two tests (a dev identity, and the Access verifier being
chosen from the settings) and static everywhere else.
"""

from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from strategy_manager.identity.application.ports import IdentityUnavailableError
from strategy_manager.identity.infrastructure import dependencies
from strategy_manager.identity.infrastructure.access_jwt import AccessJwtVerifier
from strategy_manager.identity.infrastructure.dependencies import (
    FORBIDDEN_DETAIL,
    UNAUTHORIZED_DETAIL,
    DevIdentityVerifier,
    identity_verifier_for,
    require_admin,
    verified_email,
)
from strategy_manager.shared.config import Settings, get_settings
from tests.identity_auth import (
    ADMIN_EMAIL,
    ADMIN_HEADERS,
    FORGED_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    sign_in_as_admin,
)


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(email: Annotated[str, Depends(verified_email)]) -> dict[str, str]:
        return {"email": email}

    @app.get("/admin", dependencies=[Depends(require_admin)])
    async def admin() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as api:
        yield api


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.mark.usefixtures("signed_in")
async def test_a_verified_assertion_yields_its_email(client: AsyncClient) -> None:
    response = await client.get("/who", headers=OTHER_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"email": OTHER_EMAIL}


@pytest.mark.usefixtures("signed_in")
@pytest.mark.parametrize("headers", [{}, FORGED_HEADERS])
async def test_no_or_a_forged_assertion_is_401_with_one_word(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    for path in ("/who", "/admin"):
        response = await client.get(path, headers=headers)

        assert response.status_code == 401
        assert response.json() == {"detail": UNAUTHORIZED_DETAIL}


@pytest.mark.usefixtures("signed_in")
async def test_the_admin_passes_the_admin_check(client: AsyncClient) -> None:
    response = await client.get("/admin", headers=ADMIN_HEADERS)

    assert response.status_code == 200


@pytest.mark.usefixtures("signed_in")
async def test_a_signed_in_user_who_is_not_the_admin_is_403(client: AsyncClient) -> None:
    response = await client.get("/admin", headers=OTHER_HEADERS)

    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}


async def test_the_admin_e_mail_is_compared_after_folding_case(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "admin_email", " OWNER@Example.com ")

    response = await client.get("/admin", headers=ADMIN_HEADERS)

    assert ADMIN_EMAIL == "owner@example.com"
    assert response.status_code == 200


async def test_an_unavailable_identity_is_503_not_401(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Down:
        async def verify(self, assertion: str | None) -> str:
            raise IdentityUnavailableError

    monkeypatch.setattr(dependencies, "identity_verifier_for", lambda settings: _Down())

    response = await client.get("/who", headers=ADMIN_HEADERS)

    assert response.status_code == 503


async def test_a_dev_identity_signs_every_request_in_as_that_user(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "dev_user_email", "dev@example.com")
    monkeypatch.setattr(get_settings(), "access_team_domain", "")
    monkeypatch.setattr(get_settings(), "access_aud", "")

    response = await client.get("/who")

    assert response.json() == {"email": "dev@example.com"}


def test_the_access_verifier_is_chosen_and_reused_when_access_is_configured() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        access_team_domain="acme.cloudflareaccess.com",
        access_aud="aud-tag",
    )

    first = identity_verifier_for(settings)

    assert isinstance(first, AccessJwtVerifier)
    assert identity_verifier_for(settings) is first


def test_the_dev_verifier_is_chosen_when_only_a_dev_identity_is_set() -> None:
    settings = Settings(_env_file=None, dev_user_email="dev@example.com")  # type: ignore[call-arg]

    assert isinstance(identity_verifier_for(settings), DevIdentityVerifier)

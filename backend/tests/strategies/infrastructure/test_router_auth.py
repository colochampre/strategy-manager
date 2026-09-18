"""API tests for the bearer token guarding ``/strategies``.

The assertion that matters most here is not that a bad token is refused — it
is that EVERY route on this router is refused, discovered from the router
itself rather than from a list written by hand. A list would go stale the
moment someone adds an endpoint, which is the exact failure the router-level
dependency exists to prevent; enumerating ``router.routes`` means the test
covers routes that do not exist yet.
"""

import re
from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.config import get_settings
from strategy_manager.strategies.infrastructure.auth import UNAUTHORIZED_DETAIL
from strategy_manager.strategies.infrastructure.router import router as strategies_router

TOKEN = "adm1n-t0ken"

#: Path parameters are filled with a well-formed value so that a refusal is
#: never the path converter's doing.
_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _routes() -> list[tuple[str, str]]:
    """Every (method, path) this router serves, read from the router itself.

    HEAD and OPTIONS are dropped: Starlette adds them around a registered
    method rather than as endpoints anyone declared.
    """
    pairs: list[tuple[str, str]] = []
    for route in strategies_router.routes:
        path = _PATH_PARAM.sub(str(uuid4()), getattr(route, "path", ""))
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            pairs.append((method, path))
    return pairs


def _app() -> FastAPI:
    """The router mounted on a bare application: no lifespan, no other router.

    ``create_app`` would drag in startup invariants that need a database, and
    what is under test is the router's own dependency — which travels with the
    router wherever it is mounted.
    """
    app = FastAPI()
    app.include_router(strategies_router)
    return app


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set explicitly rather than inherited from the developer's .env, so these
    assertions describe the code and not the machine."""
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


async def test_there_is_at_least_one_route_to_protect() -> None:
    """Guards the enumeration itself: a test that iterates an empty list
    passes while proving nothing."""
    assert len(_routes()) >= 4


async def test_every_registered_route_refuses_a_request_without_a_token(
    client: AsyncClient,
) -> None:
    """The structural claim. The dependency is on the router, so this holds for
    the routes below it today and for any route added later — an author who
    forgets about authentication still ships an authenticated endpoint."""
    for method, path in _routes():
        response = await client.request(method, path)

        assert response.status_code == 401, f"{method} {path} was not refused"


async def test_no_route_leaks_which_part_of_the_credential_was_wrong(
    client: AsyncClient,
) -> None:
    """One detail for every refusal, on every route. A caller who learns that
    a token is merely wrong — rather than absent, or wrongly framed — is being
    told which half of their guess to keep."""
    details = set()
    for method, path in _routes():
        for headers in (
            {},
            {"Authorization": f"Bearer {TOKEN}-wrong"},
            {"Authorization": TOKEN},
            {"Authorization": f"Basic {TOKEN}"},
        ):
            response = await client.request(method, path, headers=headers)

            assert response.status_code == 401
            details.add(response.json()["detail"])

    assert details == {UNAUTHORIZED_DETAIL}


async def test_a_wrong_token_is_refused(client: AsyncClient) -> None:
    response = await client.get(
        "/strategies", headers={"Authorization": "Bearer not-the-token"}
    )

    assert response.status_code == 401


async def test_a_missing_authorization_header_is_refused(client: AsyncClient) -> None:
    response = await client.get("/strategies")

    assert response.status_code == 401


async def test_a_header_without_the_bearer_scheme_is_refused(
    client: AsyncClient,
) -> None:
    response = await client.get("/strategies", headers={"Authorization": TOKEN})

    assert response.status_code == 401


async def test_an_unconfigured_token_refuses_even_a_request_that_sends_none(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The comparison must never be vacuous. Startup invariant 4 refuses to
    boot a deployment configured this way; this asserts the second lock, which
    is what stands if that invariant is ever removed or bypassed."""
    monkeypatch.setattr(get_settings(), "admin_api_token", "")

    for headers in ({"Authorization": "Bearer "}, {"Authorization": "Bearer"}, {}):
        response = await client.get("/strategies", headers=headers)

        assert response.status_code == 401


@pytest.mark.integration
async def test_a_correct_token_reaches_the_endpoint(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The other half: the guard refuses, it does not wall the router off."""
    from strategy_manager.shared import db as shared_db

    app = _app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        response = await api.get(
            "/strategies", headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert response.status_code == 200
    assert response.json() == []

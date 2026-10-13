"""T4, the wiring, and the route through the application ``main.py`` builds
(design addendum "open positions", sections G and L; tasks.md op.1.25).

* The router's source names ``SqlAlchemyModeOriginReader`` (in the manner of
  ``tests/test_mode_guard_wiring.py``): the reader the route iterates is the
  guard's own, never a look-alike. A structural test: it cannot tell a reader
  that is named from a reader that is used, so the invariant on real PostgreSQL
  (``test_open_positions_matches_guard``) is the other half.
* ``GET /api/positions/open`` is mounted under ``/api`` by ``create_app()`` and
  authenticated like every admin route.
"""

import inspect
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.performance.infrastructure import open_positions_router
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL

TOKEN = "adm1n-t0ken"


def test_the_router_wires_the_guards_own_sql_reader() -> None:
    source = inspect.getsource(open_positions_router.get_open_state_source)

    assert "SqlAlchemyModeOriginReader" in source


def test_the_router_module_imports_the_guards_reader_from_its_one_home() -> None:
    source = inspect.getsource(open_positions_router)

    assert (
        "from strategy_manager.execution.infrastructure.mode_origin_reader import" in source
    ), "the reader must be the guard's, imported from its own module"


@pytest.mark.integration
async def test_the_application_serves_the_route_under_api(
    pg_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.get("/api/positions/open")
        served = await client.get(
            "/api/positions/open", headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": UNAUTHORIZED_DETAIL}
    assert served.status_code == 200, served.text
    body = served.json()
    assert (body["positions"], body["orders"]) == ([], [])
    assert body["as_of"].endswith("Z")

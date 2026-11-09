"""No answer under ``/api/strategies`` is kept by a browser or a proxy (tasks.md K.D, A5).

The author's own reads carry a LINK strategy's ``share_token``: whoever holds it
opens the strategy, so it must not outlive the page in a cache. A refusal goes
through the same middleware, so it is asked too.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def client(
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


async def test_no_answer_about_the_authors_strategies_is_kept_by_a_browser_or_a_proxy(
    client: AsyncClient,
) -> None:
    listed = await client.get("/api/strategies")
    missing = await client.get(f"/api/strategies/{uuid4()}")

    assert listed.status_code == 200, listed.text
    assert missing.status_code == 404, missing.text
    assert listed.headers.get("cache-control") == "no-store"
    assert missing.headers.get("cache-control") == "no-store"

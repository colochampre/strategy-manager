"""The open-positions route shows the signed-in user's rows only (multi-user
design AD8, owner decision 16), on real PostgreSQL.

Two users hold an open position of the SAME strategy on the SAME market, one
spelled ``SOLUSDT.P`` and one ``SOLUSDT``, each with a SUBMITTED closing order.
The guard's own reader, which the worker's startup check uses without a user, is
the very class the route uses with one; the route must pass the signed-in id.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, act_as, sign_in_as_admin
from tests.owner import OWNER_ID, seed_other_user
from tests.performance.infrastructure.conftest import seed_execution_attempt
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


async def _get(factory: async_sessionmaker[AsyncSession], user_id: UUID) -> dict[str, Any]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    act_as(app, user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/positions/open", headers=ADMIN_HEADERS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_each_user_sees_only_their_own_positions_and_orders(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    strategy_id, mine, my_attempt = await _seed_allocation(pg_session_factory)
    _, theirs, their_attempt = await _seed_allocation(
        pg_session_factory, strategy_id=strategy_id, user_id=other
    )
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=strategy_id, allocation_id=mine, attempt_id=my_attempt,
            side="BUY", quantity="1", symbol="SOLUSDT.P",
        ),
        _fill(
            strategy_id=strategy_id, allocation_id=theirs, attempt_id=their_attempt,
            side="BUY", quantity="2", symbol="SOLUSDT", user_id=other,
        ),
    )
    my_order, their_order = uuid4(), uuid4()
    await seed_execution_attempt(
        pg_session_factory, attempt_id=my_order, closes_allocation_id=mine,
        exchange_order_id="1234567890123",
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=their_order, closes_allocation_id=theirs,
        exchange_order_id="9876543210987",
    )

    owner_body = await _get(pg_session_factory, OWNER_ID)
    other_body = await _get(pg_session_factory, other)

    assert [p["allocation_id"] for p in owner_body["positions"]] == [str(mine)]
    assert [p["allocation_id"] for p in other_body["positions"]] == [str(theirs)]
    # ``_seed_allocation`` also leaves each user's own SUBMITTED opening attempt.
    assert {o["attempt_id"] for o in owner_body["orders"]} == {str(my_order), str(my_attempt)}
    assert {o["attempt_id"] for o in other_body["orders"]} == {str(their_order), str(their_attempt)}

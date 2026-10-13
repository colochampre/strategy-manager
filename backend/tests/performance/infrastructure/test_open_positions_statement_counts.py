"""T7, statement counts: the open-positions read never degrades to one statement
per row (design addendum "open positions", sections G and L; tasks.md op.1.27)
[DB].

A ``before_cursor_execute`` listener counts the statements one request issues
through the application's route, snapshot statement included: four with nothing
open (the ``SET``, the guard's two reads, the submitted orders) and seven once
something is open (plus the two statements of the facts and the one of the
disagreements) however many positions and orders there are. Real PostgreSQL,
ORM schema.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.performance.infrastructure.guard_cases import (
    record_fill,
    seed_allocation,
    seed_guard_cases,
)

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record_statement(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


async def _request(
    factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, int, int]:
    """``(statements, positions, orders)`` of one request."""
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _captured_sql(engine) as statements:
            response = await client.get(
                "/api/positions/open", headers={"Authorization": f"Bearer {TOKEN}"}
            )
    assert response.status_code == 200, response.text
    body = response.json()
    return len(statements), len(body["positions"]), len(body["orders"])


async def _open_positions(factory: async_sessionmaker[AsyncSession], count: int) -> None:
    for _ in range(count):
        allocation = await seed_allocation(factory)
        await record_fill(factory, allocation, side="BUY", quantity="1", rehearsal=False)


async def test_four_statements_with_nothing_open_and_seven_with_one_position_or_twenty(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nothing = await _request(pg_session_factory, pg_engine, monkeypatch)

    await _open_positions(pg_session_factory, 1)
    one = await _request(pg_session_factory, pg_engine, monkeypatch)

    await _open_positions(pg_session_factory, 19)
    twenty = await _request(pg_session_factory, pg_engine, monkeypatch)

    assert nothing == (4, 0, 0)
    assert one == (7, 1, 0)
    assert twenty == (7, 20, 0), "the number of statements grew with the number of positions"


async def test_orders_in_flight_do_not_add_statements(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed_guard_cases(pg_session_factory)

    statements, positions, orders = await _request(pg_session_factory, pg_engine, monkeypatch)

    assert positions > 5 and orders > 5, "the seed holds many positions and many orders"
    assert statements == 7

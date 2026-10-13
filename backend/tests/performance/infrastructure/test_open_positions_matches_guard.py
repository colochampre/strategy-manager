"""T3, the invariant on real PostgreSQL (design addendum "open positions",
section L; spec admin-api "An Empty Answer Means The Mode Guard's Two Inputs Were
Empty"; tasks.md op.1.26).

The cases the guard's own integration test seeds (``guard_cases``) are written to
the database; the application's route answers; and ``SqlAlchemyModeOriginReader``
is asked, on the SAME database, for its two lists. The route holds exactly one
position per element of ``open_allocations()`` and one order per element of
``in_flight_attempts()`` plus the SUBMITTED attempts the guard cannot judge. The
SQL, the joins and the wiring are all in the loop: a LEFT join made inner, a
``WHERE`` in a facts statement or a filter in the router turns it red.

The whole request is also asserted to run on ONE database connection: the three
sources of the use case share the one snapshot session, and a source built on a
session of its own would use another connection (and, under concurrency, read
another state).
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.performance.infrastructure.guard_cases import GuardCases, seed_guard_cases

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"


@contextmanager
def _statements_with_connection(engine: AsyncEngine) -> Iterator[list[tuple[str, int]]]:
    seen: list[tuple[str, int]] = []

    def _record_statement(conn: Any, cursor: object, statement: str, *rest: object) -> None:
        seen.append((statement, id(conn.connection.dbapi_connection)))

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


async def _route(
    factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], list[tuple[str, int]]]:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with _statements_with_connection(engine) as statements:
            response = await client.get(
                "/api/positions/open", headers={"Authorization": f"Bearer {TOKEN}"}
            )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body, list(statements)


@pytest.fixture
async def cases(pg_session_factory: async_sessionmaker[AsyncSession]) -> GuardCases:
    return await seed_guard_cases(pg_session_factory)


async def test_the_route_holds_exactly_the_elements_of_the_guards_two_reads(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    cases: GuardCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with pg_session_factory() as session:
        reader = SqlAlchemyModeOriginReader(session)
        opened = list(await reader.open_allocations())
        in_flight = list(await reader.in_flight_attempts())
    # The comparison below is empty-equals-empty if the seed does nothing: the
    # reader must read what the helper claims to have written.
    assert {e.allocation_id for e in opened} == cases.open_ids
    assert {e.attempt_id for e in in_flight} == cases.in_flight_ids

    body, _ = await _route(pg_session_factory, pg_engine, monkeypatch)

    # Positions: the SAME ids, as lists, so a duplicate shows.
    assert sorted(p["allocation_id"] for p in body["positions"]) == sorted(
        str(e.allocation_id) for e in opened
    )
    by_allocation: dict[str, dict[str, Any]] = {p["allocation_id"]: p for p in body["positions"]}
    for element in opened:
        position = by_allocation[str(element.allocation_id)]
        assert position["strategy_name"] == element.strategy_name
        assert position["pool"] == {
            "exchange": element.exchange,
            "venue": element.venue,
            "settlement_currency": element.settlement_currency,
        }
        expected_origin = (
            "mixed"
            if element.holds_rehearsal_fill and element.holds_live_fill
            else "rehearsal"
            if element.holds_rehearsal_fill
            else "live"
        )
        assert position["origin"] == expected_origin

    # Orders: a superset. The guard's elements are all there, with the guard's
    # origin; the extras are exactly the SUBMITTED attempts with no order id.
    served = {o["attempt_id"]: o for o in body["orders"]}
    assert len(served) == len(body["orders"]), "an order is served twice"
    assert {str(e.attempt_id) for e in in_flight} <= set(served)
    for element in in_flight:
        order = served[str(element.attempt_id)]
        assert order["origin"] == ("rehearsal" if element.rehearsal else "live")
        assert order["strategy_name"] == element.strategy_name
    extras = set(served) - {str(e.attempt_id) for e in in_flight}
    assert extras == {str(cases.order_without_id), str(cases.order_without_id_closing)}
    assert {served[i]["origin"] for i in extras} == {"unknown"}
    assert served[str(cases.order_without_id)]["action"] == "OPEN"
    assert served[str(cases.order_without_id_closing)]["action"] == "CLOSE"
    assert str(cases.order_terminal) not in served


async def test_the_flat_and_closed_allocations_are_not_served(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    cases: GuardCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body, _ = await _route(pg_session_factory, pg_engine, monkeypatch)

    served = {p["allocation_id"] for p in body["positions"]}
    for flat in (cases.closed_two_spellings, cases.closed_rehearsal, cases.closed_base_fee_flat):
        assert str(flat) not in served


async def test_a_live_id_that_only_contains_the_marker_is_live_and_a_disabled_pool_is_served(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    cases: GuardCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body, _ = await _route(pg_session_factory, pg_engine, monkeypatch)

    by_allocation = {p["allocation_id"]: p for p in body["positions"]}
    assert by_allocation[str(cases.open_live_marker_in_id)]["origin"] == "live"
    assert by_allocation[str(cases.open_mixed)]["origin"] == "mixed"
    assert by_allocation[str(cases.open_rehearsal)]["origin"] == "rehearsal"
    disabled = by_allocation[str(cases.open_disabled_pool)]
    assert (disabled["pool"]["settlement_currency"], disabled["currency"]) == ("ETH", "ETH")
    coin_m = by_allocation[str(cases.open_coin_m_btc)]
    assert (coin_m["pool"]["exchange"], coin_m["currency"]) == ("pionex", "BTC")
    # The ledger's two spellings of one market are served as ONE market key.
    assert by_allocation[str(cases.open_two_spellings)]["markets"] == ["SOLUSDT"]
    # An allocation whose base currency cannot be told keeps its row, with the reason.
    unresolved = by_allocation[str(cases.open_unresolved)]
    assert unresolved["figures_missing"] == "UNRESOLVED_SYMBOL"
    assert unresolved["size"] is None


async def test_the_leverage_a_position_was_opened_at_is_served_with_its_stored_scale(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    cases: GuardCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body, _ = await _route(pg_session_factory, pg_engine, monkeypatch)

    by_allocation = {p["allocation_id"]: p for p in body["positions"]}
    assert by_allocation[str(cases.leveraged_allocation)]["leverage"] == "2.00000000"
    assert by_allocation[str(cases.open_rehearsal)]["leverage"] is None


async def test_every_statement_of_the_request_runs_on_one_connection(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    cases: GuardCases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard's reader, the facts and the disagreements share the snapshot
    session. A source built on a session of its own checks out another
    connection, and the snapshot would not cover it."""
    _, statements = await _route(pg_session_factory, pg_engine, monkeypatch)

    assert statements, "no statement was captured"
    connections: set[int] = {connection for _, connection in statements}
    assert len(connections) == 1, f"{len(connections)} connections served one request"
    assert statements[0][0].startswith("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")


async def test_an_empty_database_gives_an_empty_answer(
    pg_session_factory: async_sessionmaker[AsyncSession],
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body, statements = await _route(pg_session_factory, pg_engine, monkeypatch)

    assert (body["positions"], body["orders"]) == ([], [])
    assert len(statements) == 4

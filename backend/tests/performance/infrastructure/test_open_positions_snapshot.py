"""T6, the snapshot [DB] (design addendum "open positions", sections G and L).

One request must read ONE database state. The harness holds the read between its
first statement (the in-flight read) and its second (the open-allocations read);
a second connection commits an order's fill and its ``FILLED`` status in one
transaction; the read is released. The answer must be the state BEFORE the fill,
whole: the order, and not its position.

Real PostgreSQL, through the same fixtures as the neighbouring infrastructure
tests. The two events of ``HeldOpenStateSource`` are controlled by the test, and
the held read is asserted NOT done before it is released (rule R13): ordering is
proven, never slept.

The app is built here, not by ``create_app()``: the route is not registered in
``main.py`` until its own task.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.performance.application.ports import OpenStateSourcePort
from strategy_manager.performance.infrastructure import open_positions_router
from strategy_manager.performance.infrastructure.open_positions_router import (
    get_open_state_source,
    get_snapshot_session,
)
from strategy_manager.shared import db as shared_db
from tests.performance.fakes import HeldOpenStateSource
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _seed_allocation,
)
from tests.performance.infrastructure.test_performance_router import (  # noqa: F401
    _auth,
    _configure_admin_token,
)

pytestmark = pytest.mark.integration

WAIT = 10.0


async def _seed_order_in_flight(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID]:
    """A strategy, its reservation and one ``SUBMITTED`` attempt the venue already
    accepted (an order id that is not a rehearsal's). Returns
    ``(strategy_id, allocation_id, attempt_id)``."""
    strategy_id, allocation_id, attempt_id = await _seed_allocation(factory)
    async with factory() as session:
        await session.execute(
            text("UPDATE execution_attempts SET exchange_order_id = :o WHERE id = :id"),
            {"o": f"ORDER-{attempt_id}", "id": attempt_id},
        )
        await session.commit()
    return strategy_id, allocation_id, attempt_id


async def _fill_the_order(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    allocation_id: UUID,
    attempt_id: UUID,
) -> None:
    """What the worker does when the venue reports the fill: the order's fill and
    its ``FILLED`` status, committed in ONE transaction on a connection of its own."""
    async with factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            _fill(
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                attempt_id=attempt_id,
                side="BUY",
                quantity="1",
                price="100",
            )
        )
        await session.execute(
            text("UPDATE execution_attempts SET status = 'FILLED' WHERE id = :id"),
            {"id": attempt_id},
        )
        await session.commit()


def _held_app(
    factory: async_sessionmaker[AsyncSession],
    held_slot: list[HeldOpenStateSource],
    *,
    snapshot: Callable[..., AsyncIterator[AsyncSession]] | None = None,
) -> FastAPI:
    """The route over the test's own database, with the real reader wrapped in
    the held-read harness. ``snapshot`` replaces the router's snapshot dependency
    (a test of the harness uses the pass-through)."""
    app = FastAPI()
    app.include_router(open_positions_router.router, prefix="/api")

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    if snapshot is not None:
        app.dependency_overrides[get_snapshot_session] = snapshot

    def _held_source(
        session: Annotated[AsyncSession, Depends(get_snapshot_session)],
    ) -> OpenStateSourcePort:
        held = HeldOpenStateSource(SqlAlchemyModeOriginReader(session))
        held_slot.append(held)
        return held

    app.dependency_overrides[get_open_state_source] = _held_source
    return app


async def _read_held_across_a_fill(
    app: FastAPI,
    held_slot: list[HeldOpenStateSource],
    factory: async_sessionmaker[AsyncSession],
    ids: tuple[UUID, UUID, UUID],
) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.get("/api/positions/open", headers=_auth()))
        # The harness is parked between the first statement and the second.
        while not held_slot:
            await asyncio.sleep(0)
            assert not request.done(), "the request ended before the read started"
        held = held_slot[0]
        await asyncio.wait_for(held.first_done.wait(), WAIT)
        assert not request.done(), "the read was not held between its two statements"

        await _fill_the_order(factory, *ids)

        assert not request.done(), "the held read finished without being released"
        held.release.set()
        response = await asyncio.wait_for(request, WAIT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


async def test_a_fill_committed_during_the_read_is_not_seen_by_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The read is released AFTER the order's fill is committed. One snapshot means
    the answer still shows the order, and not the position the fill created."""
    ids = await _seed_order_in_flight(pg_session_factory)
    _, allocation_id, attempt_id = ids
    held_slot: list[HeldOpenStateSource] = []

    body = await _read_held_across_a_fill(
        _held_app(pg_session_factory, held_slot), held_slot, pg_session_factory, ids
    )

    assert body == {"positions": [], "orders": [str(attempt_id)]}, (
        f"the state BEFORE the fill, whole, is the order and no position "
        f"(allocation {allocation_id}); the held read answered {body}"
    )

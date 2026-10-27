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
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

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
from strategy_manager.reconciliation.infrastructure.models import ReconciliationDiscrepancyRow
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, act_as
from tests.owner import OWNER_ID, ensure_pool
from tests.performance.fakes import HeldOpenStateSource
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _seed_allocation,
)
from tests.performance.infrastructure.test_performance_router import (  # noqa: F401
    _signed_in,
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
    return act_as(app, OWNER_ID)


async def _read_held_across_a_fill(
    app: FastAPI,
    held_slot: list[HeldOpenStateSource],
    factory: async_sessionmaker[AsyncSession],
    ids: tuple[UUID, UUID, UUID],
) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.get("/api/positions/open", headers=ADMIN_HEADERS))
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
    # The whole body is pinned in ``test_open_positions_router``; what this test
    # is about is WHICH rows the one snapshot shows.
    return {
        "positions": [position["allocation_id"] for position in body["positions"]],
        "orders": [order["attempt_id"] for order in body["orders"]],
    }


async def _read_held_across(
    app: FastAPI,
    held_slot: list[HeldOpenStateSource],
    concurrent: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    """The same hold as above, with ``concurrent`` run on connections of its own
    while the read is parked; the WHOLE body is returned."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.get("/api/positions/open", headers=ADMIN_HEADERS))
        while not held_slot:
            await asyncio.sleep(0)
            assert not request.done(), "the request ended before the read started"
        held = held_slot[0]
        await asyncio.wait_for(held.first_done.wait(), WAIT)
        assert not request.done(), "the read was not held between its two statements"

        await concurrent()

        assert not request.done(), "the held read finished without being released"
        held.release.set()
        response = await asyncio.wait_for(request, WAIT)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    return body


async def test_the_facts_and_the_disagreements_are_read_in_the_same_snapshot_as_the_guards_reader(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """EVERY source the use case is given is built on the snapshot's session. While
    the read is parked after its first statement, other connections commit a
    second fill of the open allocation, a new SUBMITTED attempt and a CONFIRMED
    discrepancy naming the allocation. None of them may show: a facts source or a
    disagreement source on a session of its own would read them."""
    factory = pg_session_factory
    strategy_id, allocation_id, attempt_id = await _seed_order_in_flight(factory)
    async with factory() as session:
        await session.execute(
            text("UPDATE execution_attempts SET status = 'FILLED' WHERE id = :id"),
            {"id": attempt_id},
        )
        await session.execute(text("DELETE FROM reconciliation_discrepancies"))
        await session.commit()
    await _fill_the_order(factory, strategy_id, allocation_id, attempt_id)  # one fill: open
    held_slot: list[HeldOpenStateSource] = []

    async def _commit_from_elsewhere() -> None:
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
            await session.commit()
        await _seed_order_in_flight(factory)
        async with factory() as session:
            session.add(
                ReconciliationDiscrepancyRow(
                    id=uuid4(),
                    user_id=OWNER_ID,
                    pool_id=await ensure_pool(session, ("bybit", "usdt-m", "USDT")),
                    exchange="bybit",
                    venue="usdt-m",
                    settlement_currency="USDT",
                    symbol="SOLUSDT",
                    kind="ATTRIBUTABLE_SINGLE_ALLOCATION",
                    venue_net_base=Decimal("0"),
                    ledger_net_base=Decimal("1"),
                    open_allocation_ids=[allocation_id],
                    consecutive_scans=3,
                    status="CONFIRMED",
                    confirmed_at=datetime.now(UTC),
                    first_scan_id=uuid4(),
                    last_scan_id=uuid4(),
                )
            )
            await session.commit()

    body = await _read_held_across(
        _held_app(factory, held_slot), held_slot, _commit_from_elsewhere
    )

    (position,) = body["positions"]
    assert position["allocation_id"] == str(allocation_id)
    assert position["fill_count"] == 1, "the facts read a fill committed after the snapshot"
    assert position["venue_disagreement"] is None, (
        "the disagreements read a row committed after the snapshot"
    )
    assert body["orders"] == [], "the submitted-orders read an attempt created after the snapshot"


async def _plain_session(
    session: Annotated[AsyncSession, Depends(shared_db.get_session)],
) -> AsyncIterator[AsyncSession]:
    """The pass-through: a plain session, with no snapshot statement."""
    yield session


async def test_the_same_harness_without_the_snapshot_shows_the_mixed_state(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The harness can fail (rule R2): with the snapshot dependency replaced by the
    pass-through, the SAME held read shows the order AND its position. That is
    what makes the test above not vacuous."""
    ids = await _seed_order_in_flight(pg_session_factory)
    _, allocation_id, attempt_id = ids
    held_slot: list[HeldOpenStateSource] = []

    body = await _read_held_across_a_fill(
        _held_app(pg_session_factory, held_slot, snapshot=_plain_session),
        held_slot,
        pg_session_factory,
        ids,
    )

    assert body == {"positions": [str(allocation_id)], "orders": [str(attempt_id)]}


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

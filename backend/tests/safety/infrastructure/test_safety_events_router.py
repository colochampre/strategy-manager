"""``GET /api/safety-events`` on real PostgreSQL (subscriber-safety SS.10, spec safety-events,
"A user sees their own events in the panel").

Mounted through ``create_app()`` so the ``/api`` prefix and the router's sign-in guard are
part of what is proven, with ``get_session`` overridden to a real session.

* a user gets their own events only, and the admin gets only their own too;
* newest first, and at most 100;
* each event carries the wire the panel reads: strings in ``detail``, an instant with an
  offset, the strategy's name;
* a missing or forged assertion is a 401.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.safety.infrastructure.models import SafetyEventRow
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, FORGED_HEADERS, act_as, sign_in_as_admin
from tests.owner import OWNER_ID, seed_other_user
from tests.signals.infrastructure.conftest import seed_reservation, seed_signal_row, seed_strategy

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
_BASE = datetime(2026, 11, 17, 9, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


class World:
    """One strategy with an allocation, and a supply of closing attempts to name as the
    source of an event (each event needs its own: the source is UNIQUE)."""

    def __init__(self, factory: Factory, strategy: UUID, allocation: UUID) -> None:
        self.factory = factory
        self.strategy = strategy
        self.allocation = allocation

    async def attempts(self, count: int) -> list[UUID]:
        async with self.factory() as session:
            ids = [uuid4() for _ in range(count)]
            for attempt_id in ids:
                await session.execute(
                    text(
                        "INSERT INTO execution_attempts (id, user_id, closes_allocation_id, "
                        "exchange, venue, settlement_currency, symbol, side, quantity, status, "
                        "client_order_id) VALUES (:id, :u, :a, 'bybit', 'usdt-m', 'USDT', "
                        "'SOLUSDT', 'SELL', 1, 'FAILED', :c)"
                    ),
                    {"id": attempt_id, "u": OWNER_ID, "a": self.allocation, "c": f"c-{attempt_id}"},
                )
            await session.commit()
        return ids

    async def event(
        self,
        user: UUID,
        attempt: UUID,
        *,
        minutes: int = 0,
        kind: str = "MANUAL_CLOSE",
        detail: dict[str, str] | None = None,
    ) -> UUID:
        async with self.factory() as session:
            row = SafetyEventRow(
                user_id=user,
                kind=kind,
                strategy_id=self.strategy,
                allocation_id=self.allocation,
                exchange="bybit",
                venue="usdt-m",
                symbol="SOLUSDT",
                occurred_at=_BASE + timedelta(minutes=minutes),
                detail=detail or {"quantity": "0.5", "price": "142.1"},
                execution_attempt_id=attempt,
            )
            session.add(row)
            await session.commit()
            return row.id


@pytest.fixture
async def world(pg_session_factory: Factory) -> World:
    strategy, signal, allocation = uuid4(), uuid4(), uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy)
    await seed_signal_row(
        pg_session_factory, signal_id=signal, strategy_id=strategy, idempotency_key="k"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=allocation,
        strategy_id=strategy,
        signal_id=signal,
        status="FILLED",
    )
    return World(pg_session_factory, strategy, allocation)


async def _get(factory: Factory, user_id: UUID | None) -> tuple[int, dict[str, Any]]:
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    if user_id is not None:
        act_as(app, user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/safety-events", headers=ADMIN_HEADERS)
    body: dict[str, Any] = response.json()
    return response.status_code, body


async def test_each_user_gets_their_own_events_only(
    pg_session_factory: Factory, world: World
) -> None:
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    mine, theirs = await world.attempts(2)
    my_event = await world.event(OWNER_ID, mine)
    their_event = await world.event(other, theirs, kind="STOP_FIRED")

    status, owner_body = await _get(pg_session_factory, OWNER_ID)
    other_status, other_body = await _get(pg_session_factory, other)

    assert (status, other_status) == (200, 200)
    assert [event["id"] for event in owner_body["events"]] == [str(my_event)]
    assert [event["id"] for event in other_body["events"]] == [str(their_event)]


async def test_the_admin_sees_their_own_events_and_nobody_elses(
    pg_session_factory: Factory, world: World
) -> None:
    async with pg_session_factory() as session:
        subscriber = await seed_other_user(session)
        await session.commit()
    admin_attempt, subscriber_attempt = await world.attempts(2)
    await world.event(subscriber, subscriber_attempt)
    admin_event = await world.event(OWNER_ID, admin_attempt)

    status, body = await _get(pg_session_factory, OWNER_ID)

    assert status == 200
    assert [event["id"] for event in body["events"]] == [str(admin_event)]


async def test_an_event_carries_the_wire_the_panel_reads(
    pg_session_factory: Factory, world: World
) -> None:
    [attempt] = await world.attempts(1)
    event_id = await world.event(
        OWNER_ID, attempt, kind="STOP_FIRED", detail={"quantity": "0.5", "trigger_price": "142.1"}
    )

    _, body = await _get(pg_session_factory, OWNER_ID)

    assert body == {
        "events": [
            {
                "id": str(event_id),
                "kind": "STOP_FIRED",
                "strategy_id": str(world.strategy),
                "strategy_name": f"strategy-{world.strategy}",
                "allocation_id": str(world.allocation),
                "exchange": "bybit",
                "venue": "usdt-m",
                "symbol": "SOLUSDT",
                "occurred_at": "2026-11-17T09:00:00Z",
                "detail": {"quantity": "0.5", "trigger_price": "142.1"},
            }
        ]
    }


async def test_events_come_newest_first(pg_session_factory: Factory, world: World) -> None:
    first, second, third = await world.attempts(3)
    oldest = await world.event(OWNER_ID, first, minutes=1)
    newest = await world.event(OWNER_ID, second, minutes=30)
    middle = await world.event(OWNER_ID, third, minutes=10)

    _, body = await _get(pg_session_factory, OWNER_ID)

    assert [event["id"] for event in body["events"]] == [str(newest), str(middle), str(oldest)]


async def test_at_most_the_hundred_newest_events_are_listed(
    pg_session_factory: Factory, world: World
) -> None:
    attempts = await world.attempts(105)
    ids = [await world.event(OWNER_ID, attempt, minutes=n) for n, attempt in enumerate(attempts)]

    _, body = await _get(pg_session_factory, OWNER_ID)

    listed = [event["id"] for event in body["events"]]
    assert listed == [str(event_id) for event_id in reversed(ids[5:])]


async def test_a_user_with_no_events_gets_an_empty_list(pg_session_factory: Factory) -> None:
    status, body = await _get(pg_session_factory, OWNER_ID)

    assert (status, body) == (200, {"events": []})


async def test_a_forged_assertion_is_refused(pg_session_factory: Factory) -> None:
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/safety-events", headers=FORGED_HEADERS)

    assert response.status_code == 401

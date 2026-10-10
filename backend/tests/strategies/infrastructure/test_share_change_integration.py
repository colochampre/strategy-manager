"""A change of a strategy's share leaves everything already made untouched (spec:
capital-allocation "A Changed Share Of The Pool Applies From The Next Allocation
Only"; design.md, unit 12f addendum, section A U3 and section C; tasks.md
12f.9.8).

The code already behaves so: the share is read when an opening is sized, the
request is computed from it BEFORE the pool lock, and nothing after that reads the
share again. These tests pin that, each with a mutation recorded in its task:

- a reservation already held keeps its amount, its recorded pool capital, its
  status, and the ledger keeps its rows;
- the next opening is sized with the stored share, read through the real policy
  adapter;
- the change takes NO pool lock: a PATCH completes while another connection still
  HOLDS the pool's advisory lock (the lock-hold harness used the other way round:
  here the second actor must NOT wait, so an edit that makes a share change queue
  behind an allocation turns this red).

Real PostgreSQL on the ORM schema: every assertion reads rows by their keys and no
constraint or index the ORM schema lacks decides an outcome.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.percent import requested_from_percent
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.policy_adapter import StrategyPolicyAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _record,
    _seed_allocation,
)
from tests.strategies.infrastructure.test_router import (  # noqa: F401
    _auth,
    _authenticated_client,
    _configure_admin_token,
)

pytestmark = pytest.mark.integration

_WAIT = 5.0  # seconds; only ever a ceiling for a hung test, never a pacing delay
BYBIT = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
OPENED_AT = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture
async def client(pg_session_factory: Factory) -> AsyncIterator[AsyncClient]:  # noqa: F811
    async for api in _authenticated_client(pg_session_factory):
        yield api


async def _strategy_holding_a_reservation(factory: Factory, share: str) -> tuple[UUID, UUID]:
    """A strategy with ``share`` as its share of the pool, holding one reservation of
    100 USDT made when the pool held 1000, and the ledger rows of its opening."""
    strategy_id, allocation_id, attempt_id = await _seed_allocation(
        factory, pool_total_at_open="1000"
    )
    async with factory() as session:
        await session.execute(
            text("UPDATE strategies SET allocation_percent = CAST(:share AS numeric)"),
            {"share": share},
        )
        await session.execute(
            text("UPDATE reservations SET amount = 100 WHERE id = :id"), {"id": allocation_id}
        )
        await session.commit()
    await _record(
        factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="BUY",
            quantity="2",
            price="50",
            symbol="STXUSDT.P",
            filled_at=OPENED_AT,
        ),
    )
    return strategy_id, allocation_id


async def _rows(factory: Factory, table: str) -> list[tuple[Any, ...]]:
    async with factory() as session:
        result = await session.execute(text(f"SELECT * FROM {table} ORDER BY id"))  # noqa: S608
        return [tuple(row) for row in result.all()]


async def _stored_share(factory: Factory, strategy_id: UUID) -> Decimal:
    async with factory() as session:
        value = await session.scalar(
            text("SELECT allocation_percent FROM strategies WHERE id = :id"), {"id": strategy_id}
        )
    assert isinstance(value, Decimal)
    return value


async def test_a_changed_share_leaves_an_existing_reservation_unchanged(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """S1, with a share of 10, holds a reservation of 100 USDT made when the pool
    held 1000. The share goes to 25 through the PATCH: the amount, the recorded pool
    capital, the status and the ledger rows are exactly as they were, and so is the
    attempt that opened the position."""
    strategy_id, allocation_id = await _strategy_holding_a_reservation(pg_session_factory, "10")
    reservations_before = await _rows(pg_session_factory, "reservations")
    ledger_before = await _rows(pg_session_factory, "ledger_entries")
    attempts_before = await _rows(pg_session_factory, "execution_attempts")
    assert len(reservations_before) == 1
    assert len(ledger_before) == 1
    assert len(attempts_before) == 1

    patched = await client.patch(
        f"/strategies/{strategy_id}", json={"allocation_percent": "25"}, headers=_auth()
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["allocation_percent"] == "25"
    assert await _stored_share(pg_session_factory, strategy_id) == Decimal("25")
    reservations_after = await _rows(pg_session_factory, "reservations")
    assert reservations_after == reservations_before
    assert await _rows(pg_session_factory, "ledger_entries") == ledger_before
    assert await _rows(pg_session_factory, "execution_attempts") == attempts_before
    # Spelled out, so a failure names the figure and not two tuples.
    async with pg_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT amount, pool_total_at_open, status FROM reservations WHERE id = :id"
                ),
                {"id": allocation_id},
            )
        ).one()
    assert (row.amount, row.pool_total_at_open, row.status) == (
        Decimal("100"),
        Decimal("1000"),
        "SUBMITTED",
    )


async def test_the_next_opening_is_sized_with_the_new_share(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The share is read through the REAL policy adapter, before and after the
    PATCH, each time from a fresh session, as the worker reads it per signal. The
    request for a pool of 1000 is then 100 and 250, computed by the engine's own
    function."""
    strategy_id, _ = await _strategy_holding_a_reservation(pg_session_factory, "10")

    async def policy_share() -> Decimal:
        async with pg_session_factory() as session:
            snapshot = await StrategyPolicyAdapter(
                SqlAlchemyStrategyRepository(session)
            ).policy_for(strategy_id)
        return snapshot.allocation_percent

    before = await policy_share()
    patched = await client.patch(
        f"/strategies/{strategy_id}", json={"allocation_percent": "25"}, headers=_auth()
    )
    after = await policy_share()

    assert patched.status_code == 200, patched.text
    assert requested_from_percent(Decimal("1000"), before) == Decimal("100")
    assert requested_from_percent(Decimal("1000"), after) == Decimal("250")


async def test_a_share_change_completes_while_the_pools_advisory_lock_is_held(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The lock-hold harness used the other way round: a second connection holds
    the pool's advisory lock (as an allocation in flight would), and the PATCH must
    NOT wait for it. The PATCH takes the strategy's row lock and no advisory lock."""
    strategy_id, _ = await _strategy_holding_a_reservation(pg_session_factory, "10")

    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(BYBIT))
        task: asyncio.Task[Any] | None = None
        try:
            async with pg_session_factory() as watcher:
                held = await watcher.scalar(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted"
                    )
                )
            assert held and held >= 1, "the holder does not hold the pool lock"

            task = asyncio.create_task(
                client.patch(
                    f"/strategies/{strategy_id}",
                    json={"allocation_percent": "25"},
                    headers=_auth(),
                )
            )
            await asyncio.wait({task}, timeout=_WAIT)

            assert task.done(), "the share change waited for the pool's advisory lock"
            response = task.result()
        finally:
            await holder.rollback()  # releases the pool lock, whatever happened above
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert response.status_code == 200, response.text
    assert await _stored_share(pg_session_factory, strategy_id) == Decimal("25")

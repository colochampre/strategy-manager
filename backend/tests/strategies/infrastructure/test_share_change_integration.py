"""A PATCH of a strategy takes no pool lock, and never touches its share (spec:
capital-allocation; design.md, unit 12f addendum, section A U3; tasks.md 12f.9.8,
reworked by C.4b).

Until C.4b the PATCH also changed the strategy's share, and these tests pinned that a
change leaves a held reservation untouched and sizes only the NEXT opening. The share is
the subscription's now, and ``process_signal`` keeps reading the strategy's own copy
until C.6, so those two properties have no route to exercise here: C.6 re-homes them on
``ChangeShare``. What stays true of the PATCH, and is pinned below:

- it completes while another connection still HOLDS the pool's advisory lock (the
  lock-hold harness used the other way round: here the second actor must NOT wait, so an
  edit that makes a PATCH queue behind an allocation turns this red);
- it leaves the stored share, the held reservation and the ledger as they were.

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
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.identity_auth import ADMIN_HEADERS
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401
from tests.owner import OWNER_ID
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _record,
    _seed_allocation,
)
from tests.strategies.infrastructure.test_router import (  # noqa: F401
    _authenticated_client,
    _signed_in,
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
    """A strategy with ``share`` as its own copy of the share, holding one reservation of
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


async def test_a_patch_leaves_the_share_and_an_existing_reservation_unchanged(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """S1, with a share of 10, holds a reservation of 100 USDT made when the pool
    held 1000. A PATCH of its name and fill mode changes neither the stored share, nor
    the reservation, the ledger or the attempt that opened the position."""
    strategy_id, _ = await _strategy_holding_a_reservation(pg_session_factory, "10")
    reservations_before = await _rows(pg_session_factory, "reservations")
    ledger_before = await _rows(pg_session_factory, "ledger_entries")
    attempts_before = await _rows(pg_session_factory, "execution_attempts")
    assert len(reservations_before) == 1
    assert len(ledger_before) == 1
    assert len(attempts_before) == 1

    patched = await client.patch(
        f"/strategies/{strategy_id}",
        json={"name": "renamed", "fill_mode": "SKIP"},
        headers=ADMIN_HEADERS,
    )

    assert patched.status_code == 200, patched.text
    assert await _stored_share(pg_session_factory, strategy_id) == Decimal("10")
    assert await _rows(pg_session_factory, "reservations") == reservations_before
    assert await _rows(pg_session_factory, "ledger_entries") == ledger_before
    assert await _rows(pg_session_factory, "execution_attempts") == attempts_before


async def test_a_patch_completes_while_the_pools_advisory_lock_is_held(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The lock-hold harness used the other way round: a second connection holds
    the pool's advisory lock (as an allocation in flight would), and the PATCH must
    NOT wait for it. The PATCH takes the strategy's row lock and no advisory lock."""
    strategy_id, _ = await _strategy_holding_a_reservation(pg_session_factory, "10")

    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(OWNER_ID, BYBIT))
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
                    json={"name": "renamed while locked"},
                    headers=ADMIN_HEADERS,
                )
            )
            await asyncio.wait({task}, timeout=_WAIT)

            assert task.done(), "the PATCH waited for the pool's advisory lock"
            response = task.result()
        finally:
            await holder.rollback()  # releases the pool lock, whatever happened above
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "renamed while locked"

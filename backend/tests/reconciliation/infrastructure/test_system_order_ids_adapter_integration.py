"""Integration test: ``SystemOrderIdsAdapter.holds_any()`` against real
PostgreSQL (owner decision 66 Q2, 2026-10-16; design.md PR 15 addendum C8).

Whether any of a set of venue order ids is the ``exchange_order_id`` of an
``execution_attempts`` row of the SAME ``(exchange, venue,
settlement_currency)``. The attempt is seeded as ``STXUSDT.P`` (the ledger's
and the attempt's spelling) while the venue's fills, whose order ids are asked
about, come as ``STXUSDT`` (R21): the question is keyed on the order id and
the pool, never on a symbol.
"""

from collections.abc import Sequence
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.infrastructure.system_order_ids_adapter import (
    SystemOrderIdsAdapter,
)
from tests.owner import OWNER_ID
from tests.reconciliation.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

POOL: PoolKey = ("bybit", "usdt-m", "USDT")


async def _seed_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    exchange_order_id: str | None,
    pool: PoolKey = POOL,
) -> None:
    exchange, venue, settlement_currency = pool
    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools "
                "(user_id, exchange, venue, settlement_currency, min_order_size) "
                "VALUES (:owner, :exchange, :venue, :settlement_currency, 5) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "owner": OWNER_ID,
                "exchange": exchange,
                "venue": venue,
                "settlement_currency": settlement_currency,
            },
        )
        await session.commit()
    await seed_strategy(
        session_factory,
        strategy_id=strategy_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )
    await seed_execution_attempt(
        session_factory,
        attempt_id=uuid4(),
        reservation_id=reservation_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol="STXUSDT.P",
        status="FILLED",
        exchange_order_id=exchange_order_id,
    )


async def _holds_any(
    session_factory: async_sessionmaker[AsyncSession],
    order_ids: Sequence[str],
    pool: PoolKey = POOL,
) -> bool:
    async with session_factory() as session:
        return await SystemOrderIdsAdapter(session).holds_any(pool, order_ids)


async def test_an_order_id_of_an_attempt_of_the_same_pool_is_found(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attempt(pg_session_factory, exchange_order_id="ord-1")

    assert await _holds_any(pg_session_factory, ["ord-9", "ord-1"]) is True


async def test_an_order_id_nobody_placed_is_not_found(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attempt(pg_session_factory, exchange_order_id="ord-1")

    assert await _holds_any(pg_session_factory, ["ord-8", "ord-9"]) is False


async def test_another_pools_attempt_is_not_found(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attempt(
        pg_session_factory, exchange_order_id="ord-1", pool=("binance", "usdt-m", "USDT")
    )
    await _seed_attempt(
        pg_session_factory, exchange_order_id="ord-2", pool=("bybit", "spot", "USDT")
    )
    await _seed_attempt(
        pg_session_factory, exchange_order_id="ord-3", pool=("bybit", "usdt-m", "BTC")
    )

    assert await _holds_any(pg_session_factory, ["ord-1", "ord-2", "ord-3"]) is False


async def test_an_attempt_with_no_order_id_answers_no(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attempt(pg_session_factory, exchange_order_id=None)

    assert await _holds_any(pg_session_factory, ["ord-1"]) is False


async def test_an_empty_set_answers_no(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attempt(pg_session_factory, exchange_order_id="ord-1")

    assert await _holds_any(pg_session_factory, []) is False


async def test_the_whole_set_is_one_statement_not_one_per_id(
    pg_engine: AsyncEngine,
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_attempt(pg_session_factory, exchange_order_id="ord-40")
    statements: list[str] = []

    def _record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(pg_engine.sync_engine, "before_cursor_execute", _record)
    try:
        answer = await _holds_any(pg_session_factory, [f"ord-{n}" for n in range(50)])
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", _record)

    assert answer is True
    assert len(statements) == 1

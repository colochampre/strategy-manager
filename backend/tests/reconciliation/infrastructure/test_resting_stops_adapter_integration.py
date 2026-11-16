"""Integration test: ``RestingStopsAdapter.resting_symbols()`` against real PostgreSQL
(subscriber-safety SS.7).

Which markets of one user's pool have a protective stop that is still ``RESTING``. The stop
row has no settlement currency of its own, so the pool is read through the opening attempt it
protects. The stop is seeded as ``DOGEUSDT.P`` (the alert's spelling, which is what the row
records); the adapter returns it as recorded and the scan maps it to its market key.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyProtectiveStopRepository,
)
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.infrastructure.resting_stops_adapter import (
    RestingStopsAdapter,
)
from tests.owner import OWNER_ID, seed_other_user
from tests.reconciliation.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

POOL: PoolKey = ("bybit", "usdt-m", "USDT")
OTHER_POOL: PoolKey = ("binance", "usdt-m", "USDT")


async def _seed_stop(
    factory: async_sessionmaker[AsyncSession],
    *,
    pool: PoolKey = POOL,
    status: StopStatus = StopStatus.RESTING,
    symbol: str = "DOGEUSDT.P",
) -> None:
    exchange, venue, settlement_currency = pool
    strategy_id, signal_id, reservation_id, attempt_id = uuid4(), uuid4(), uuid4(), uuid4()
    async with factory() as session:
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
        factory,
        strategy_id=strategy_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )
    await seed_signal(
        factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
    )
    await seed_execution_attempt(
        factory,
        attempt_id=attempt_id,
        reservation_id=reservation_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        status="FILLED",
    )
    async with factory() as session:
        await SqlAlchemyProtectiveStopRepository(session).insert(
            OWNER_ID,
            ProtectiveStop(
                id=uuid4(),
                execution_attempt_id=attempt_id,
                allocation_id=reservation_id,
                exchange=exchange,
                venue=venue,
                symbol=symbol,
                position_side=PositionSide.LONG,
                stop_loss_pct=Decimal("10"),
                trigger_price=Decimal("0.0597"),
                status=status,
            ),
        )
        await session.commit()


async def _resting(
    factory: async_sessionmaker[AsyncSession], pool: PoolKey = POOL, user_id: UUID = OWNER_ID
) -> list[str]:
    async with factory() as session:
        return list(await RestingStopsAdapter(session).resting_symbols(user_id, pool))


async def test_a_resting_stop_of_the_pool_is_listed_as_the_row_records_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_stop(pg_session_factory)

    assert await _resting(pg_session_factory) == ["DOGEUSDT.P"]


@pytest.mark.parametrize(
    "status",
    [
        StopStatus.PENDING,
        StopStatus.FIRED,
        StopStatus.FAILED,
        StopStatus.GONE,
        StopStatus.VOID,
        StopStatus.SIMULATED,
    ],
)
async def test_a_stop_that_is_not_resting_is_not_listed(
    pg_session_factory: async_sessionmaker[AsyncSession], status: StopStatus
) -> None:
    """A stop the watcher decided (FIRED, GONE) or never confirmed is not the watcher's to
    hold the scan for."""
    await _seed_stop(pg_session_factory, status=status)

    assert await _resting(pg_session_factory) == []


async def test_a_stop_of_another_pool_is_not_listed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_stop(pg_session_factory, pool=OTHER_POOL)

    assert await _resting(pg_session_factory) == []
    assert await _resting(pg_session_factory, OTHER_POOL) == ["DOGEUSDT.P"]


async def test_a_stop_of_the_same_exchange_and_venue_in_another_currency_is_not_listed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The stop row records no currency: the pool is read through the opening attempt."""
    other_currency: PoolKey = ("bybit", "usdt-m", "BTC")
    await _seed_stop(pg_session_factory, pool=other_currency)

    assert await _resting(pg_session_factory) == []
    assert await _resting(pg_session_factory, other_currency) == ["DOGEUSDT.P"]


async def test_another_users_stop_is_not_listed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Multi-user AD8: one user's resting stop never holds another user's scan."""
    await _seed_stop(pg_session_factory)
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()

    assert await _resting(pg_session_factory) == ["DOGEUSDT.P"]
    assert await _resting(pg_session_factory, user_id=other) == []


async def test_two_stops_on_one_market_list_it_once(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_stop(pg_session_factory)
    await _seed_stop(pg_session_factory)

    assert await _resting(pg_session_factory) == ["DOGEUSDT.P"]

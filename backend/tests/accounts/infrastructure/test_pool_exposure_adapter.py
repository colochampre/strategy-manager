"""``PoolExposureAdapter`` against real PostgreSQL (tasks.md 6e.6, 6e.9;
owner decision 22).

The adapter answers what blocks deleting an exchange's key, and the answer is
POOL-WIDE: every strategy bound to the pool, never one. The same three queries
``StrategyExposureAdapter`` composes, without a strategy filter, plus the
strategies still enabled.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.ports import EnabledStrategy, PoolExposure
from strategy_manager.accounts.infrastructure.pool_exposure_adapter import PoolExposureAdapter
from strategy_manager.ledger.domain.ledger_entry import LedgerEntry
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.accounts.pool_seed import (
    NOW,
    POOL,
    seed_execution_attempt,
    seed_live_reservation,
    seed_open_position,
    seed_reservation,
    seed_signal,
    seed_strategy,
    set_strategy_enabled,
)
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration

OTHER_POOL = ("pionex", "spot", "USDT")


async def _exposure(
    factory: async_sessionmaker[AsyncSession], pool: tuple[str, str, str] = POOL
) -> PoolExposure:
    async with factory() as session:
        return await PoolExposureAdapter.over(session).exposure(pool)


async def _strategy(
    factory: async_sessionmaker[AsyncSession],
    *,
    enabled: bool = False,
    pool: tuple[str, str, str] = POOL,
) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(
        factory,
        strategy_id=strategy_id,
        exchange=pool[0],
        venue=pool[1],
        settlement_currency=pool[2],
        enabled=enabled,
    )
    return strategy_id


async def test_an_empty_pool_has_no_exposure(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    await _strategy(pg_session_factory)

    assert (await _exposure(pg_session_factory)).is_empty()


async def test_exposure_sees_every_strategy_bound_to_pool_not_just_one(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """One strategy holds a position, another a live reservation, a third a
    SUBMITTED attempt, a fourth is enabled. A check scoped to one strategy would
    see one of the four."""
    holder = await _strategy(pg_session_factory)
    reserver = await _strategy(pg_session_factory)
    submitter = await _strategy(pg_session_factory)
    enabled = await _strategy(pg_session_factory, enabled=True)
    quiet = await _strategy(pg_session_factory)

    allocation = await seed_open_position(pg_session_factory, strategy_id=holder, symbol="ETHUSDT")
    reservation = await seed_live_reservation(pg_session_factory, strategy_id=reserver)
    submitted_reservation = await seed_live_reservation(
        pg_session_factory, strategy_id=submitter, status="SUBMITTED"
    )
    attempt = uuid4()
    await seed_execution_attempt(
        pg_session_factory, attempt_id=attempt, reservation_id=submitted_reservation
    )

    exposure = await _exposure(pg_session_factory)

    assert [s.id for s in exposure.enabled_strategies] == [enabled]
    assert quiet not in [s.id for s in exposure.enabled_strategies]
    assert exposure.symbols == frozenset({"ETHUSDT"})
    assert exposure.allocations == (allocation,)
    assert set(exposure.live_reservations) == {reservation, submitted_reservation}
    assert exposure.in_flight_attempts == (attempt,)


async def test_enabled_strategies_are_named_with_their_id_and_name(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory, enabled=True)

    exposure = await _exposure(pg_session_factory)

    assert exposure.enabled_strategies == (
        EnabledStrategy(id=strategy_id, name=f"strategy-{strategy_id}"),
    )


async def test_a_disabled_strategy_is_not_reported_as_enabled(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory, enabled=True)
    await set_strategy_enabled(pg_session_factory, strategy_id, False)

    assert (await _exposure(pg_session_factory)).enabled_strategies == ()


async def test_another_pools_exposure_is_not_this_pools(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    other = await _strategy(pg_session_factory, enabled=True, pool=OTHER_POOL)
    await seed_open_position(
        pg_session_factory, strategy_id=other, symbol="BTCUSDT", pool=OTHER_POOL
    )
    await seed_live_reservation(pg_session_factory, strategy_id=other, pool=OTHER_POOL)

    assert (await _exposure(pg_session_factory)).is_empty()
    assert not (await _exposure(pg_session_factory, OTHER_POOL)).is_empty()


async def test_a_closed_allocation_and_a_terminal_reservation_are_not_exposure(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    allocation = await seed_open_position(
        pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT", quantity=Decimal("2")
    )
    # Close it exactly: a SELL of the same quantity on the same allocation.
    close_attempt = uuid4()
    await seed_execution_attempt(
        pg_session_factory,
        attempt_id=close_attempt,
        closes_allocation_id=allocation,
        symbol="ETHUSDT",
        status="FILLED",
        exchange_order_id=f"ord-{close_attempt}",
    )
    async with pg_session_factory() as session:
        await SqlAlchemyLedgerRepository(session).insert(
            LedgerEntry(
                id=uuid4(),
                strategy_id=strategy_id,
                allocation_id=allocation,
                execution_attempt_id=close_attempt,
                exchange=POOL[0],
                venue=POOL[1],
                settlement_currency=POOL[2],
                symbol="ETHUSDT",
                side="SELL",
                quantity=Decimal("2"),
                price=Decimal("1"),
                fee=Decimal("0"),
                fee_currency=POOL[2],
                notional=Decimal("2"),
                exchange_order_id=f"ord-{close_attempt}",
                exchange_fill_id=f"fill-{close_attempt}",
                filled_at=NOW,
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    for status in ("FILLED", "EXPIRED", "FAILED"):
        await seed_live_reservation(pg_session_factory, strategy_id=strategy_id, status=status)

    assert (await _exposure(pg_session_factory)).is_empty()


async def test_two_allocations_on_the_same_market_are_reported_one_each(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Two strategies open on the same market, one under TradingView's spelling:
    the market is reported once, the allocations twice."""
    first = await _strategy(pg_session_factory)
    second = await _strategy(pg_session_factory)
    a = await seed_open_position(pg_session_factory, strategy_id=first, symbol="STXUSDT.P")
    b = await seed_open_position(pg_session_factory, strategy_id=second, symbol="STXUSDT")

    exposure = await _exposure(pg_session_factory)

    assert exposure.symbols == frozenset({"STXUSDT"})
    assert set(exposure.allocations) == {a, b}


async def test_a_reservation_past_its_expiry_but_not_yet_swept_still_blocks(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """``terminal_at IS NULL`` is the question, not ``expires_at``: until the
    sweeper terminates it, the row still says it holds capital."""
    strategy_id = await _strategy(pg_session_factory)
    signal_id = uuid4()
    reservation = uuid4()
    await seed_signal(
        pg_session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation,
        strategy_id=strategy_id,
        signal_id=signal_id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    assert (await _exposure(pg_session_factory)).live_reservations == (reservation,)


async def test_the_adapter_reads_only_and_writes_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    strategy_id = await _strategy(pg_session_factory, enabled=True)
    await seed_open_position(pg_session_factory, strategy_id=strategy_id, symbol="ETHUSDT")
    async with pg_session_factory() as session:
        before = (await session.execute(text("SELECT count(*) FROM ledger_entries"))).scalar_one()

    await _exposure(pg_session_factory)

    async with pg_session_factory() as session:
        after = (await session.execute(text("SELECT count(*) FROM ledger_entries"))).scalar_one()
    assert before == after == 1

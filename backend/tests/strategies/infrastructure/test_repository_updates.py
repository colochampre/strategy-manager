"""Integration: listing strategies and writing the mutable half of one.

Against real PostgreSQL, because the guarantee being tested is partly the
database's: ``update`` must not be able to move a strategy between capital
pools, and the only convincing proof of that is a row that did not move.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.money import Currency, Venue
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)
from strategy_manager.strategies.infrastructure.pool_catalog import (
    SqlAlchemyPoolCatalog,
)
from strategy_manager.strategies.infrastructure.repository import (
    SqlAlchemyStrategyRepository,
)

pytestmark = pytest.mark.integration


def _strategy(
    name: str,
    *,
    venue: Venue = Venue.SPOT,
    currency: Currency = Currency.USDT,
    enabled: bool = False,
    percent: str = "100",
) -> Strategy:
    return Strategy(
        id=uuid4(),
        name=name,
        policy=AllocationPolicy(
            venue=venue,
            settlement_currency=currency,
            fill_mode=FillMode.PARTIAL,
            allocation_percent=AllocationPercent(Decimal(percent)),
        ),
        enabled=enabled,
    )


async def test_listing_is_ordered_by_name_so_it_is_stable(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        for name in ("SOL 4h", "AAVE 4h", "BAT v1.3"):
            await repository.insert(_strategy(name))
        await session.commit()

    async with pg_session_factory() as session:
        listed = await SqlAlchemyStrategyRepository(session).list_all()

    assert [s.name for s in listed] == ["AAVE 4h", "BAT v1.3", "SOL 4h"]


async def test_an_empty_registry_lists_nothing_rather_than_failing(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        assert await SqlAlchemyStrategyRepository(session).list_all() == []


async def test_update_writes_the_mutable_fields(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy = _strategy("original", enabled=False, percent="100")

    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).insert(strategy)
        await session.commit()

    changed = Strategy(
        id=strategy.id,
        name="renamed",
        policy=AllocationPolicy(
            venue=strategy.policy.venue,
            settlement_currency=strategy.policy.settlement_currency,
            fill_mode=FillMode.SKIP,
            allocation_percent=AllocationPercent(Decimal("25")),
        ),
        enabled=True,
    )

    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).update(changed)
        await session.commit()

    async with pg_session_factory() as session:
        found = await SqlAlchemyStrategyRepository(session).get_by_id(strategy.id)

    assert found is not None
    assert found.name == "renamed"
    assert found.enabled is True
    assert found.policy.fill_mode is FillMode.SKIP
    assert found.policy.allocation_percent.value == Decimal("25")


async def test_update_cannot_move_a_strategy_to_another_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The adapter leaves ``venue`` and ``settlement_currency`` out of the
    statement, so even a caller that hands it a moved strategy cannot move
    the row. Switching pools routes the close of an open position to the
    wrong adapter -- the holding stays open while the system believes it
    closed."""
    strategy = _strategy("spot strategy", venue=Venue.SPOT, currency=Currency.USDT)

    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).insert(strategy)
        await session.commit()

    moved = Strategy(
        id=strategy.id,
        name=strategy.name,
        policy=AllocationPolicy(
            venue=Venue.USDT_M,
            settlement_currency=Currency.USDT,
            fill_mode=strategy.policy.fill_mode,
            allocation_percent=strategy.policy.allocation_percent,
        ),
        enabled=True,
    )

    async with pg_session_factory() as session:
        await SqlAlchemyStrategyRepository(session).update(moved)
        await session.commit()

    async with pg_session_factory() as session:
        found = await SqlAlchemyStrategyRepository(session).get_by_id(strategy.id)

    assert found is not None
    assert found.policy.venue is Venue.SPOT
    # The rest of the update still landed, so this is a targeted refusal
    # rather than the whole write being dropped.
    assert found.enabled is True


async def test_updating_a_row_that_is_not_there_fails_loudly(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        with pytest.raises(LookupError):
            await SqlAlchemyStrategyRepository(session).update(_strategy("ghost"))


async def test_the_pool_catalog_reports_only_enabled_pools(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A disabled pool is invisible to the allocation engine, so a strategy
    must not be allowed to point at one."""
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false "
                "WHERE venue = 'coin-m' AND settlement_currency = 'ETH'"
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        pools = await SqlAlchemyPoolCatalog(session).enabled_pools()

    assert (Venue.SPOT, Currency.USDT) in pools
    assert (Venue.COIN_M, Currency.ETH) not in pools

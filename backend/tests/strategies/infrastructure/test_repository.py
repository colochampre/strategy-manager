"""Integration test: SqlAlchemyStrategyRepository insert + get_by_id round
trip (supplemental RED coverage for tasks.md 3.7 — SqlAlchemyStrategyRepository
implementation, mirroring tests/signals/infrastructure/test_repository.py)."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.money import Currency, Venue
from strategy_manager.strategies.domain.strategy import AllocationPolicy, FillMode, Strategy
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository

pytestmark = pytest.mark.integration


def _strategy(strategy_id: object) -> Strategy:
    return Strategy(
        id=strategy_id,  # type: ignore[arg-type]
        name=f"strategy-{strategy_id}",
        policy=AllocationPolicy(
            venue=Venue.SPOT, settlement_currency=Currency.USDT, fill_mode=FillMode.PARTIAL
        ),
        enabled=True,
    )


async def test_insert_then_get_by_id_round_trips_the_strategy(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()

    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        await repository.insert(_strategy(strategy_id))
        await session.commit()

    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        found = await repository.get_by_id(strategy_id)

    assert found is not None
    assert found.id == strategy_id
    assert found.enabled is True
    assert found.policy.fill_mode == FillMode.PARTIAL
    assert found.policy.venue == Venue.SPOT
    assert found.policy.settlement_currency == Currency.USDT


async def test_get_by_id_returns_none_for_unknown_id(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        found = await repository.get_by_id(uuid4())

    assert found is None

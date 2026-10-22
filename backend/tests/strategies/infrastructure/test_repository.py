"""Integration test: SqlAlchemyStrategyRepository insert + get_by_id round
trip (supplemental RED coverage for tasks.md 3.7 — SqlAlchemyStrategyRepository
implementation, mirroring tests/signals/infrastructure/test_repository.py)."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.domain.strategy import AllocationPolicy, FillMode, Strategy
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from tests.owner import OWNER_ID, seed_user

pytestmark = pytest.mark.integration


def _strategy(strategy_id: object, author_id: UUID = OWNER_ID) -> Strategy:
    return Strategy(
        id=strategy_id,  # type: ignore[arg-type]
        name=f"strategy-{strategy_id}",
        policy=AllocationPolicy(exchange=Exchange.PIONEX,
            venue=Venue.SPOT, settlement_currency=Currency.USDT, fill_mode=FillMode.PARTIAL
        ),
        author_id=author_id,
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


async def test_a_registered_strategy_round_trips_its_author(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Multi-user design AD2: a strategy carries its author. A second user, not
    the owner every other seed defaults to, so a read that returned the owner
    (or any constant) is told apart."""
    strategy_id = uuid4()
    async with pg_session_factory() as session:
        author = await seed_user(session, f"author-{strategy_id}@example.com")
        await SqlAlchemyStrategyRepository(session).insert(_strategy(strategy_id, author))
        await session.commit()

    async with pg_session_factory() as session:
        found = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
        listed = await SqlAlchemyStrategyRepository(session).list_all()

    assert found is not None
    assert found.author_id == author
    assert [s.author_id for s in listed if s.id == strategy_id] == [author]


async def test_get_by_id_returns_none_for_unknown_id(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        repository = SqlAlchemyStrategyRepository(session)
        found = await repository.get_by_id(uuid4())

    assert found is None

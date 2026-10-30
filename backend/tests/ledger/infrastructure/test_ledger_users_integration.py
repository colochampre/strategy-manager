"""The ledger reads that are scoped to a user, or deliberately global, beyond
the three the position projections already cover (multi-user design AD8) [DB].

``distinct_symbols_for_pool`` is the deleting user's own; the two
``distinct_users_for_*`` reads and ``distinct_symbols_for_strategy`` are global
by design (the admin's archive of a strategy, the DRY_RUN book's seed).
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.strategies.infrastructure.exposure_adapter import StrategyExposureAdapter
from tests.accounts.pool_seed import POOL, seed_open_position
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.owner import OWNER_ID, seed_other_user

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


async def _two_users_on_one_market(factory: Factory) -> tuple[UUID, UUID, UUID, UUID]:
    """The owner and another user each hold an open position on the same
    market, under strategies of their own. Returns ``(other_user,
    owner_strategy, other_strategy, other_allocation)``."""
    async with factory() as session:
        other = await seed_other_user(session)
        await session.commit()
    owner_strategy, other_strategy = uuid4(), uuid4()
    await seed_strategy(factory, strategy_id=owner_strategy)
    await seed_strategy(factory, strategy_id=other_strategy, author_id=other)
    await seed_open_position(factory, strategy_id=owner_strategy, symbol="ETHUSDT")
    other_allocation = await seed_open_position(
        factory, strategy_id=other_strategy, symbol="SOLUSDT", user_id=other
    )
    return other, owner_strategy, other_strategy, other_allocation


async def test_the_symbols_of_a_pool_are_the_asking_users_own(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    other, *_ = await _two_users_on_one_market(pg_session_factory)

    async with pg_session_factory() as session:
        repository = SqlAlchemyLedgerRepository(session)
        owners = await repository.distinct_symbols_for_pool(OWNER_ID, *POOL)
        others = await repository.distinct_symbols_for_pool(other, *POOL)

    assert owners == frozenset({"ETHUSDT"})
    assert others == frozenset({"SOLUSDT"})


async def test_the_users_of_a_strategy_are_read_across_users(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    other, owner_strategy, other_strategy, _ = await _two_users_on_one_market(
        pg_session_factory
    )

    async with pg_session_factory() as session:
        repository = SqlAlchemyLedgerRepository(session)
        of_owner_strategy = await repository.distinct_users_for_strategy(*POOL, owner_strategy)
        of_other_strategy = await repository.distinct_users_for_strategy(*POOL, other_strategy)
        symbols_of_other_strategy = await repository.distinct_symbols_for_strategy(
            *POOL, other_strategy
        )

    assert of_owner_strategy == frozenset({OWNER_ID})
    assert of_other_strategy == frozenset({other})
    assert symbols_of_other_strategy == frozenset({"SOLUSDT"})


async def test_archiving_sees_a_position_held_by_a_user_other_than_the_owner(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The admin's archive is global: a strategy authored by another user, with
    an open position in that user's pool, still reports its exposure."""
    _, _, other_strategy, other_allocation = await _two_users_on_one_market(
        pg_session_factory
    )
    async with pg_session_factory() as session:
        ledger = SqlAlchemyLedgerRepository(session)
        exposure = await StrategyExposureAdapter(
            ledger=ledger,
            symbol_holdings=ReadSymbolHoldings(ledger),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ).exposure(other_strategy, POOL)

    assert exposure.symbols == frozenset({"SOLUSDT"})
    assert exposure.allocations == (other_allocation,)

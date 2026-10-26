"""Every performance use case hands the signed-in user's id to each source it
reads through (multi-user design AD8; tasks.md B.3). The sources filter on it;
these tests prove the use case does not drop it on the way.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.application.read_operation_fills import ReadOperationFills
from strategy_manager.performance.application.read_pool_performance import ReadPoolPerformance
from strategy_manager.performance.application.read_strategy_performance import (
    ReadStrategyPerformance,
)
from strategy_manager.performance.application.read_strategy_trades import ReadStrategyTrades
from strategy_manager.performance.domain.operation import OperationFill
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.owner import OWNER_ID
from tests.performance.fakes import (
    FakeDisagreementSource,
    FakeFactsSource,
    FakeFillsSource,
    FakeOpenStateReader,
    FakeOperationFillsSource,
    FakePricingSource,
    FixedClock,
)
from tests.performance.open_state_cases import open_element

POOL_KEY = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
STRATEGY = UUID(int=1)
ALLOCATION = UUID(int=10)
# Never the fixture owner: a use case that fell back to OWNER_ID would be seen.
USER = UUID("0a1b2c3d-0000-4000-8000-0000000000b1")
assert USER != OWNER_ID


async def test_pool_performance_asks_the_source_as_that_user() -> None:
    source = FakeFillsSource([])

    await ReadPoolPerformance(source, FixedClock(NOW)).read(USER, POOL_KEY)

    assert source.users == [USER]


async def test_strategy_performance_asks_the_source_as_that_user() -> None:
    source = FakeFillsSource([])

    await ReadStrategyPerformance(source, FixedClock(NOW)).read(USER, STRATEGY, POOL_KEY)

    assert source.users == [USER]


async def test_strategy_trades_ask_the_fills_as_that_user() -> None:
    source = FakeFillsSource([])

    await ReadStrategyTrades(source, FakePricingSource()).read(USER, STRATEGY, POOL_KEY)

    assert source.users == [USER]


async def test_operation_fills_ask_the_source_as_that_user() -> None:
    fill = OperationFill(
        filled_at=NOW,
        side="BUY",
        price=Decimal("1"),
        quantity=Decimal("1"),
        fee=Decimal("0"),
        fee_currency="USDT",
        rehearsal=False,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
    )
    source = FakeOperationFillsSource({(STRATEGY, ALLOCATION): [fill]})

    await ReadOperationFills(source).read(USER, STRATEGY, POOL_KEY, ALLOCATION)

    assert source.users == [USER]


async def test_open_positions_ask_all_three_sources_as_that_user() -> None:
    state = FakeOpenStateReader(opened=[open_element(rehearsal=False, live=True)])
    facts = FakeFactsSource()
    disagreements = FakeDisagreementSource()

    await ReadOpenPositions(state, facts, disagreements).read(USER)

    assert state.users == [USER, USER]
    assert facts.users == [USER, USER]
    assert disagreements.users == [USER]

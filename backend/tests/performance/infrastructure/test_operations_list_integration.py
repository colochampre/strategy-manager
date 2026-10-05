"""Integration tests: a strategy's operations, listed with and without rehearsal
rows, on the ONE ledger of unit 9p.4 (``operations_ledger`` in this package's
``conftest.py``; design.md, addendum "a strategy's operations", section H) [DB].

Real PostgreSQL on the ORM schema, fills written through ``RecordFill`` (the
production write path). Nothing here is produced by the simulated exchange.

**Binding testing lesson**: a symbol has three spellings. The real operations
open as ``STXUSDT.P`` and close as ``STXUSDT``; the rehearsal operations open as
``STXUSDT_PERP`` and close as ``STXUSDT.P``. Every operation is asserted as pair
``STXUSDT`` and base currency ``STX``, and no assertion compares two spellings as
text.
"""

import logging
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.performance.application.ports import PoolFills
from strategy_manager.performance.application.read_pool_performance import ReadPoolPerformance
from strategy_manager.performance.application.read_strategy_performance import (
    ReadStrategyPerformance,
)
from strategy_manager.performance.application.read_strategy_trades import (
    ReadStrategyTrades,
    TradeCursor,
    TradeItem,
)
from strategy_manager.performance.domain.curve import PoolPerformance
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.performance.domain.operation import RehearsalPricing
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.performance.infrastructure.rehearsal_pricing_source import (
    SqlAlchemyRehearsalPricingSource,
)
from tests.performance.fakes import FixedClock
from tests.performance.infrastructure.conftest import (
    OPERATIONS_T0,
    OperationsLedger,
    add_rehearsal_operations,
    build_real_operations,
)
from tests.performance.infrastructure.test_allocation_fills_source import BYBIT

LOGGER = "strategy_manager.performance.application.read_strategy_trades"
NOW = OPERATIONS_T0 + timedelta(days=30)

pytestmark = pytest.mark.integration


async def _pool_fills(factory: async_sessionmaker[AsyncSession]) -> PoolFills:
    async with factory() as session:
        return await SqlAlchemyAllocationFillsSource(session).pool_fills(BYBIT)


async def test_the_operations_ledger_holds_what_the_design_says(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger
    fills = await _pool_fills(pg_session_factory)

    live_ids = {group.allocation_id for group in fills.groups}
    rehearsal_ids = {group.allocation_id for group in fills.rehearsal_groups}
    assert live_ids == {
        ledger.real_long,
        ledger.real_short,
        ledger.open_real,
        ledger.mixed,
        ledger.other,
    }
    assert rehearsal_ids == {
        ledger.open_rehearsal,
        ledger.mixed,
        ledger.fixed_one,
        ledger.alert_small,
        ledger.alert_of_one,
        ledger.opened_at_one_closed_at_alert,
    }
    # The mixed allocation is the only one in both sets.
    assert live_ids & rehearsal_ids == {ledger.mixed}
    assert all(group.rehearsal for group in fills.rehearsal_groups)
    assert not any(group.rehearsal for group in fills.groups)
    assert fills.rehearsal_fill_count == 11

    live = derive_trades(fills.groups)
    assert {trade.allocation_id for trade in live.closed} == {
        ledger.real_long,
        ledger.real_short,
        ledger.mixed,
        ledger.other,
    }
    assert live.open_trade_count == 1  # the open real position

    rehearsal = derive_trades(fills.rehearsal_groups)
    assert {trade.allocation_id for trade in rehearsal.closed} == {
        ledger.mixed,
        ledger.fixed_one,
        ledger.alert_small,
        ledger.alert_of_one,
        ledger.opened_at_one_closed_at_alert,
    }
    assert rehearsal.open_trade_count == 1  # the open rehearsal position
    assert {trade.pair for trade in live.closed + rehearsal.closed} == {"STXUSDT"}


async def test_the_operations_ledger_spells_each_side_as_the_design_says(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    """The fixture is only as good as the spellings it writes: the real LONG opens
    as TradingView's and closes as the venue's, the rehearsal operation opens as
    Pionex's and closes as TradingView's."""
    ledger = operations_ledger
    fills = await _pool_fills(pg_session_factory)

    def spelled(allocation_id: object, side: str, *, rehearsal: bool) -> set[str]:
        groups = fills.rehearsal_groups if rehearsal else fills.groups
        return {g.symbol for g in groups if g.allocation_id == allocation_id and g.side == side}

    assert spelled(ledger.real_long, "BUY", rehearsal=False) == {"STXUSDT.P"}
    assert spelled(ledger.real_long, "SELL", rehearsal=False) == {"STXUSDT"}
    assert spelled(ledger.fixed_one, "BUY", rehearsal=True) == {"STXUSDT_PERP"}
    assert spelled(ledger.fixed_one, "SELL", rehearsal=True) == {"STXUSDT.P"}

    # The real LONG's three opening fills fold into one BUY group of 1000.
    long_buy = next(
        g for g in fills.groups if g.allocation_id == ledger.real_long and g.side == "BUY"
    )
    assert (long_buy.quantity, long_buy.notional) == (Decimal("1000"), Decimal("448"))

    async with pg_session_factory() as session:
        allowed = (
            await session.execute(
                text("SELECT DISTINCT allowed_pairs FROM strategies ORDER BY 1")
            )
        ).all()
    assert [row[0] for row in allowed] == [["STXUSDT"]]


async def _list(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    *,
    limit: int = 50,
    before: TradeCursor | None = None,
    include_rehearsal: bool | None = None,
) -> list[TradeItem]:
    """The strategy's list, read as the router reads it. ``include_rehearsal`` is
    passed only when given, so the default request is the one under test."""
    async with factory() as session:
        reader = ReadStrategyTrades(
            SqlAlchemyAllocationFillsSource(session), SqlAlchemyRehearsalPricingSource(session)
        )
        if include_rehearsal is None:
            page = await reader.read(strategy_id, BYBIT, limit=limit, before=before)
        else:
            page = await reader.read(
                strategy_id, BYBIT, limit=limit, before=before, include_rehearsal=include_rehearsal
            )
        return list(page.trades)


async def test_the_default_list_is_the_real_operations_only(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    items = await _list(pg_session_factory, operations_ledger.strategy_id)

    assert [item.trade.allocation_id for item in items] == list(operations_ledger.real_closed)
    assert [item.rehearsal for item in items] == [False, False, False]
    assert [item.pricing for item in items] == [None, None, None]


async def test_the_opted_in_list_adds_the_four_rehearsal_rows_with_their_classification(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    items = await _list(pg_session_factory, ledger.strategy_id, include_rehearsal=True)

    assert [item.trade.allocation_id for item in items] == [
        *ledger.rehearsal_closed,
        *ledger.real_closed,
    ]
    rehearsal = items[:4]
    assert [item.rehearsal for item in rehearsal] == [True] * 4
    assert [item.pricing for item in rehearsal] == [
        RehearsalPricing.FIXED_ONE,  # opened at 1, closed at its alert's price
        RehearsalPricing.ALERT,  # filled at 1 against an alert of exactly 1
        RehearsalPricing.ALERT,  # filled at its alert's price, a small quantity
        RehearsalPricing.FIXED_ONE,  # filled at 1 against an alert of 0.4512
    ]
    real = items[4:]
    assert [(item.rehearsal, item.pricing) for item in real] == [(False, None)] * 3


async def test_every_operation_reads_pair_stxusdt_and_base_currency_stx_under_every_spelling(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    items = await _list(pg_session_factory, operations_ledger.strategy_id, include_rehearsal=True)

    assert len(items) == 7
    assert {item.trade.pair for item in items} == {"STXUSDT"}
    assert [item.figures is not None for item in items] == [True] * 7
    assert {item.figures.base_currency for item in items if item.figures} == {"STX"}


async def test_the_mixed_allocation_is_listed_once_as_a_real_row_and_one_warning_names_it(
    pg_session_factory: async_sessionmaker[AsyncSession],
    operations_ledger: OperationsLedger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ledger = operations_ledger

    with caplog.at_level(logging.INFO, logger=LOGGER):
        items = await _list(pg_session_factory, ledger.strategy_id, include_rehearsal=True)

    mixed = [item for item in items if item.trade.allocation_id == ledger.mixed]
    assert [item.rehearsal for item in mixed] == [False]
    # Its closed_at is the real round trip's last fill, not the rehearsal one's.
    assert mixed[0].trade.closed_at == OPERATIONS_T0 + timedelta(hours=5, minutes=30)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(ledger.mixed) in warnings[0].getMessage()


def _without_rehearsal_count(report: PoolPerformance) -> PoolPerformance:
    return replace(report, exclusions=replace(report.exclusions, rehearsal_fill_count=0))


async def test_the_reports_are_identical_with_and_without_the_rehearsal_rows_in_the_ledger(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The ledger is built twice in this module's one database: first the real
    operations alone, then the rehearsal rows added to it. Every total is read
    both times. Only ``rehearsal_fill_count`` may differ: it counts what the
    totals ignore."""
    real = await build_real_operations(pg_session_factory)

    async def reports() -> tuple[PoolPerformance, PoolPerformance, tuple[object, ...]]:
        async with pg_session_factory() as session:
            source = SqlAlchemyAllocationFillsSource(session)
            pool = await ReadPoolPerformance(source, FixedClock(NOW)).read(BYBIT)
            strategy = await ReadStrategyPerformance(source, FixedClock(NOW)).read(
                real.strategy_id, BYBIT
            )
            return pool, strategy.performance, strategy.by_pair

    pool_before, strategy_before, by_pair_before = await reports()
    await add_rehearsal_operations(pg_session_factory, real)
    pool_after, strategy_after, by_pair_after = await reports()

    # Not vacuous: the totals hold the real operations and nothing else.
    assert (pool_before.closed_trade_count, strategy_before.closed_trade_count) == (4, 3)
    assert pool_before.exclusions.rehearsal_fill_count == 0
    assert strategy_before.exclusions.rehearsal_fill_count == 0
    assert pool_after.exclusions.rehearsal_fill_count == 11
    assert _without_rehearsal_count(pool_after) == pool_before
    assert _without_rehearsal_count(strategy_after) == strategy_before
    assert by_pair_after == by_pair_before
    assert len(by_pair_before) >= 1


async def test_the_rehearsal_fill_count_still_counts_every_rehearsal_fill(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    """11 fills: the open position's 1, the mixed allocation's 2 and the four
    round trips' 8. Open and mixed allocations are counted too."""
    async with pg_session_factory() as session:
        source = SqlAlchemyAllocationFillsSource(session)
        pool = await ReadPoolPerformance(source, FixedClock(NOW)).read(BYBIT)
        strategy = await ReadStrategyPerformance(source, FixedClock(NOW)).read(
            operations_ledger.strategy_id, BYBIT
        )
        other = await ReadStrategyPerformance(source, FixedClock(NOW)).read(
            operations_ledger.other_strategy_id, BYBIT
        )

    assert pool.exclusions.rehearsal_fill_count == 11
    assert strategy.performance.exclusions.rehearsal_fill_count == 11
    assert other.performance.exclusions.rehearsal_fill_count == 0


async def test_the_cursor_pages_across_both_kinds_exactly_once(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger
    expected = [*ledger.rehearsal_closed, *ledger.real_closed]

    walked: list[UUID] = []
    pages: list[int] = []
    cursor: TradeCursor | None = None
    while True:
        async with pg_session_factory() as session:
            reader = ReadStrategyTrades(
                SqlAlchemyAllocationFillsSource(session),
                SqlAlchemyRehearsalPricingSource(session),
            )
            page = await reader.read(
                ledger.strategy_id, BYBIT, limit=2, before=cursor, include_rehearsal=True
            )
        walked += [item.trade.allocation_id for item in page.trades]
        pages.append(len(page.trades))
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        assert len(pages) < 10, "the walk did not terminate"

    assert walked == expected
    assert pages == [2, 2, 2, 1]


async def test_a_strategys_list_never_contains_another_strategys_operation(
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    ledger = operations_ledger

    mine = await _list(pg_session_factory, ledger.strategy_id, include_rehearsal=True)
    theirs = await _list(pg_session_factory, ledger.other_strategy_id, include_rehearsal=True)

    assert ledger.other not in [item.trade.allocation_id for item in mine]
    assert [item.trade.allocation_id for item in theirs] == [ledger.other]
    assert [item.rehearsal for item in theirs] == [False]

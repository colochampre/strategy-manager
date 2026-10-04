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

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.performance.application.ports import PoolFills
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from tests.performance.infrastructure.conftest import OperationsLedger
from tests.performance.infrastructure.test_allocation_fills_source import BYBIT

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

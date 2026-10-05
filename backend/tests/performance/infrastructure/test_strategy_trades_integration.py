"""Integration test: ``ReadStrategyTrades`` over the real
``SqlAlchemyAllocationFillsSource`` on PostgreSQL [DB] (tasks.md 3d.4, the
"+1ms" lesson).

Trades are written through ``RecordFill`` (the production write path), so the
instants the keyset compares are the ones ``timestamptz`` actually stores and
returns, not the ones a fake was handed. The pagination itself is applied over
the derived trades in Python (design.md section 11, "Where pagination
happens"), so what this proves is that the whole path holds at the boundary:
two trades closing at the same instant straddle a page edge and neither is lost
or repeated, and a cursor round-tripped through its wire form resumes in place.

**Binding testing lesson**: the open leg is spelled ``STXUSDT.P`` and the close
``STXUSDT`` (Bybit's own name); Pionex would write ``STXUSDT_PERP``.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.performance.application.read_strategy_trades import (
    ReadStrategyTrades,
    TradeCursor,
    TradesPage,
)
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.performance.infrastructure.rehearsal_pricing_source import (
    SqlAlchemyRehearsalPricingSource,
)
from tests.performance.infrastructure.conftest import OPERATIONS_T0, OperationsLedger
from tests.performance.infrastructure.test_allocation_fills_source import (
    BYBIT,
    _fill,
    _record,
    _seed_allocation,
)

pytestmark = pytest.mark.integration

# A microsecond part that is not zero, so a cursor that lost precision would
# stop matching the stored value.
CLOSE = datetime(2026, 9, 21, 12, 0, 0, 123456, tzinfo=UTC)


async def _closed_trade(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    closed_at: datetime,
    *,
    pnl_price: str = "110",
) -> UUID:
    """One allocation of ``strategy_id``, bought at 100 and sold at
    ``pnl_price`` at ``closed_at``. Returns the allocation id."""
    _, allocation_id, attempt_id = await _seed_allocation(factory, strategy_id=strategy_id)
    await _record(
        factory,
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="BUY",
            quantity="1",
            price="100",
            filled_at=closed_at - timedelta(hours=1),
        ),
        _fill(
            strategy_id=strategy_id,
            allocation_id=allocation_id,
            attempt_id=attempt_id,
            side="SELL",
            quantity="1",
            price=pnl_price,
            symbol="STXUSDT",
            filled_at=closed_at,
        ),
    )
    return allocation_id


async def _page(
    factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    *,
    limit: int,
    before: TradeCursor | None = None,
) -> TradesPage:
    async with factory() as session:
        reader = ReadStrategyTrades(
            SqlAlchemyAllocationFillsSource(session), SqlAlchemyRehearsalPricingSource(session)
        )
        return await reader.read(strategy_id, BYBIT, limit=limit, before=before)


def _ids(page: TradesPage) -> list[UUID]:
    return [item.trade.allocation_id for item in page.trades]


async def test_keyset_pagination_on_closed_at_and_allocation_id_two_trades_same_millisecond_across_page_boundary(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Three trades close at the very same instant, one 1 ms later and one 1 ms
    earlier, and the page size is two: the boundary falls between tied trades.
    Every trade is served exactly once, newest first, ties broken by
    allocation id descending. The cursor goes through its wire form (ISO-8601
    text and UUID text) between pages."""
    strategy_id, _, _ = await _seed_allocation(pg_session_factory)
    tied = [await _closed_trade(pg_session_factory, strategy_id, CLOSE) for _ in range(3)]
    ms = timedelta(milliseconds=1)
    later = await _closed_trade(pg_session_factory, strategy_id, CLOSE + ms)
    earlier = await _closed_trade(pg_session_factory, strategy_id, CLOSE - ms)
    expected = [later, *sorted(tied, reverse=True), earlier]

    walked: list[UUID] = []
    cursor: TradeCursor | None = None
    pages = 0
    while True:
        page = await _page(pg_session_factory, strategy_id, limit=2, before=cursor)
        walked += _ids(page)
        pages += 1
        if page.next_cursor is None:
            break
        cursor = TradeCursor(
            closed_at=datetime.fromisoformat(page.next_cursor.closed_at.isoformat()),
            allocation_id=UUID(str(page.next_cursor.allocation_id)),
        )
        assert pages < 10

    assert walked == expected
    assert len(set(walked)) == 5
    assert pages == 3


async def test_the_page_boundary_between_tied_trades_is_exact_on_real_rows(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The boundary the task names, made explicit: page 1 ends on the middle of
    three tied trades, and page 2 holds precisely the third."""
    strategy_id, _, _ = await _seed_allocation(pg_session_factory)
    tied = sorted(
        [await _closed_trade(pg_session_factory, strategy_id, CLOSE) for _ in range(3)],
        reverse=True,
    )

    first = await _page(pg_session_factory, strategy_id, limit=2)
    assert _ids(first) == tied[:2]
    assert first.next_cursor == TradeCursor(closed_at=CLOSE, allocation_id=tied[1])

    second = await _page(pg_session_factory, strategy_id, limit=2, before=first.next_cursor)
    assert _ids(second) == [tied[2]]
    assert second.next_cursor is None


async def test_a_trade_closing_between_two_page_reads_neither_repeats_nor_hides_any(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Page 1 is served, THEN another trade closes (later than all of them),
    then page 2 is read from the cursor. Page 2 is unchanged; the new trade
    is at the top of the next read from the start."""
    strategy_id, _, _ = await _seed_allocation(pg_session_factory)
    a = await _closed_trade(pg_session_factory, strategy_id, CLOSE)
    b = await _closed_trade(pg_session_factory, strategy_id, CLOSE + timedelta(minutes=1))
    c = await _closed_trade(pg_session_factory, strategy_id, CLOSE + timedelta(minutes=2))
    first = await _page(pg_session_factory, strategy_id, limit=2)
    assert _ids(first) == [c, b]

    fresh = await _closed_trade(pg_session_factory, strategy_id, CLOSE + timedelta(minutes=10))
    second = await _page(pg_session_factory, strategy_id, limit=2, before=first.next_cursor)
    from_top = await _page(pg_session_factory, strategy_id, limit=10)

    assert _ids(second) == [a]
    assert _ids(from_top) == [fresh, c, b, a]


async def test_another_strategys_trades_in_the_same_pool_are_not_listed(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    mine, _, _ = await _seed_allocation(pg_session_factory)
    theirs, _, _ = await _seed_allocation(pg_session_factory)
    own = await _closed_trade(pg_session_factory, mine, CLOSE)
    await _closed_trade(pg_session_factory, theirs, CLOSE)

    page = await _page(pg_session_factory, mine, limit=10)

    assert _ids(page) == [own]


async def test_a_trade_closing_between_two_page_reads_neither_repeats_nor_hides_any_with_rehearsal_rows_in_the_fixture(  # noqa: E501
    pg_session_factory: async_sessionmaker[AsyncSession], operations_ledger: OperationsLedger
) -> None:
    """The property of the test above, kept green on the one ledger and with
    rehearsal rows asked for: page 1 holds the two newest rehearsal rows, THEN a
    real trade closes later than all of them, then page 2 is read from the cursor.
    Page 2 is unchanged and the new trade tops the next read from the start."""
    ledger = operations_ledger

    async def read(
        limit: int, before: TradeCursor | None = None
    ) -> TradesPage:
        async with pg_session_factory() as session:
            reader = ReadStrategyTrades(
                SqlAlchemyAllocationFillsSource(session),
                SqlAlchemyRehearsalPricingSource(session),
            )
            return await reader.read(
                ledger.strategy_id, BYBIT, limit=limit, before=before, include_rehearsal=True
            )

    first = await read(2)
    assert _ids(first) == [
        ledger.opened_at_one_closed_at_alert,
        ledger.alert_of_one,
    ]

    _, fresh, attempt = await _seed_allocation(pg_session_factory, strategy_id=ledger.strategy_id)
    closed_at = OPERATIONS_T0 + timedelta(days=2)
    await _record(
        pg_session_factory,
        _fill(
            strategy_id=ledger.strategy_id,
            allocation_id=fresh,
            attempt_id=attempt,
            side="BUY",
            quantity="1",
            symbol="STXUSDT.P",
            filled_at=closed_at - timedelta(hours=1),
        ),
        _fill(
            strategy_id=ledger.strategy_id,
            allocation_id=fresh,
            attempt_id=attempt,
            side="SELL",
            quantity="1",
            price="110",
            symbol="STXUSDT",
            filled_at=closed_at,
        ),
    )
    second = await read(10, first.next_cursor)
    from_top = await read(10)

    assert _ids(second) == [
        ledger.alert_small,
        ledger.fixed_one,
        *ledger.real_closed,
    ]
    assert _ids(from_top) == [
        fresh,
        ledger.opened_at_one_closed_at_alert,
        ledger.alert_of_one,
        *_ids(second),
    ]

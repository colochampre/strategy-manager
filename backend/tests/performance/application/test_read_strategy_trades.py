"""Unit tests: ``ReadStrategyTrades`` -- one strategy's closed trades, newest
first, in keyset pages on ``(closed_at, allocation_id)`` (design.md section 14
"Pagination"; tasks.md 3d.4).

The source is a fake; the domain is the real one. The same boundary is proven
against real PostgreSQL in
``tests/performance/infrastructure/test_strategy_trades_integration.py``.

**Why keyset on the pair, never ``closed_at`` alone**: two trades can close in
the same millisecond (the "+1ms" lesson). A page that ends between them and
resumes with ``closed_at < cursor`` loses the second; one that resumes with
``closed_at <= cursor`` repeats the first. Only the tuple orders them.

**Binding testing lesson**: a symbol has three spellings. Every trade below is
opened as ``STXUSDT.P`` and closed as ``STXUSDT``.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.read_strategy_trades import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidPageRequest,
    ReadStrategyTrades,
    TradeCursor,
    TradesPage,
)
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.performance.fakes import FakeFillsSource

POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
T0 = datetime(2026, 9, 21, 12, 0, 0, 123000, tzinfo=UTC)
LOGGER = "strategy_manager.performance.application.read_strategy_trades"
S1 = uuid4()
S2 = uuid4()


def _id(n: int) -> UUID:
    return UUID(int=n)


def _group(
    strategy_id: UUID,
    allocation_id: UUID,
    side: str,
    notional: str,
    *,
    symbol: str,
    at: datetime,
    capital: str | None = "1000",
    exchange: str = "bybit",
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        exchange=exchange,
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        side=side,
        fee_currency="USDT",
        quantity=Decimal("1"),
        notional=Decimal(notional),
        fee=Decimal("0"),
        first_filled_at=at,
        last_filled_at=at,
        pool_total_at_open=None if capital is None else Decimal(capital),
        rehearsal=False,
    )


def _closed(
    allocation_id: UUID,
    closed_at: datetime,
    *,
    strategy_id: UUID = S1,
    pnl: str = "10",
    capital: str | None = "1000",
    exchange: str = "bybit",
) -> list[FillGroup]:
    opened = closed_at - timedelta(hours=1)
    return [
        _group(
            strategy_id, allocation_id, "BUY", "100",
            symbol="STXUSDT.P", at=opened, capital=capital, exchange=exchange,
        ),
        _group(
            strategy_id, allocation_id, "SELL", str(Decimal("100") + Decimal(pnl)),
            symbol="STXUSDT", at=closed_at, capital=capital, exchange=exchange,
        ),
    ]


def _ids(page: TradesPage) -> list[UUID]:
    return [item.trade.allocation_id for item in page.trades]


async def _walk(reader: ReadStrategyTrades, limit: int) -> list[TradesPage]:
    pages: list[TradesPage] = []
    cursor: TradeCursor | None = None
    while True:
        page = await reader.read(S1, POOL, limit=limit, before=cursor)
        pages.append(page)
        if page.next_cursor is None:
            return pages
        cursor = page.next_cursor
        assert len(pages) < 50, "the walk did not terminate"


async def test_keyset_pagination_on_closed_at_and_allocation_id_two_trades_same_millisecond_across_page_boundary() -> (  # noqa: E501
    None
):
    """Three trades close at the very same instant, and the page size is two,
    so the boundary falls BETWEEN tied trades. Newest first with the id as the
    tie-break: 3, 2 | 1. Nothing is lost and nothing is repeated."""
    groups = _closed(_id(1), T0) + _closed(_id(2), T0) + _closed(_id(3), T0)
    reader = ReadStrategyTrades(FakeFillsSource(groups))

    first = await reader.read(S1, POOL, limit=2)
    assert _ids(first) == [_id(3), _id(2)]
    assert first.next_cursor == TradeCursor(closed_at=T0, allocation_id=_id(2))

    second = await reader.read(S1, POOL, limit=2, before=first.next_cursor)
    assert _ids(second) == [_id(1)]
    assert second.next_cursor is None


async def test_a_trade_one_millisecond_either_side_of_a_tie_orders_around_it() -> None:
    groups = (
        _closed(_id(9), T0 + timedelta(milliseconds=1))
        + _closed(_id(1), T0)
        + _closed(_id(2), T0)
        + _closed(_id(0), T0 - timedelta(milliseconds=1))
    )

    pages = await _walk(ReadStrategyTrades(FakeFillsSource(groups)), limit=1)

    assert [_ids(p) for p in pages] == [[_id(9)], [_id(2)], [_id(1)], [_id(0)]]


async def test_a_cursor_inside_a_tie_keeps_the_lower_ids_and_drops_the_higher() -> None:
    """The exact trap of paging on ``closed_at`` alone: a cursor at
    ``(T0, 2)`` must exclude 3 (already served) and include 1 (not yet)."""
    groups = _closed(_id(1), T0) + _closed(_id(2), T0) + _closed(_id(3), T0)
    reader = ReadStrategyTrades(FakeFillsSource(groups))

    page = await reader.read(S1, POOL, limit=10, before=TradeCursor(T0, _id(2)))

    assert _ids(page) == [_id(1)]


async def test_walking_every_page_yields_each_trade_exactly_once_newest_first() -> None:
    groups: list[FillGroup] = []
    for n in range(1, 8):
        groups += _closed(_id(n), T0 + timedelta(minutes=n // 2))  # pairs of ties

    pages = await _walk(ReadStrategyTrades(FakeFillsSource(groups)), limit=3)

    walked = [i for p in pages for i in _ids(p)]
    assert walked == [_id(7), _id(6), _id(5), _id(4), _id(3), _id(2), _id(1)]
    assert [len(p.trades) for p in pages] == [3, 3, 1]


async def test_an_exactly_full_last_page_has_no_next_cursor() -> None:
    groups = _closed(_id(1), T0) + _closed(_id(2), T0 + timedelta(seconds=1))

    page = await ReadStrategyTrades(FakeFillsSource(groups)).read(S1, POOL, limit=2)

    assert len(page.trades) == 2
    assert page.next_cursor is None


async def test_a_trade_that_closes_between_two_page_reads_neither_repeats_nor_hides_any() -> None:
    """A trade that closes after page 1 was served closes NOW, later than every
    trade already served, so it sorts before the first page: page 2 (from the
    cursor) is unchanged, no trade is repeated and none is lost. The new trade
    shows on the next read from the top."""
    old = _closed(_id(1), T0) + _closed(_id(2), T0 + timedelta(minutes=1))
    old += _closed(_id(3), T0 + timedelta(minutes=2))
    first = await ReadStrategyTrades(FakeFillsSource(old)).read(S1, POOL, limit=2)
    assert _ids(first) == [_id(3), _id(2)]

    grown = old + _closed(_id(4), T0 + timedelta(minutes=10))
    reader = ReadStrategyTrades(FakeFillsSource(grown))
    second = await reader.read(S1, POOL, limit=2, before=first.next_cursor)
    from_top = await reader.read(S1, POOL, limit=5)

    assert _ids(second) == [_id(1)]
    assert _ids(from_top) == [_id(4), _id(3), _id(2), _id(1)]


async def test_a_late_booked_close_older_than_the_cursor_appears_when_reached() -> None:
    """A trade whose last fill is DATED before the cursor (a booked close) and
    that becomes closed between two reads sorts after the cursor: page 2
    includes it, once. One dated before the page-1 trades but after the cursor
    would be reached in order too; only a trade that lands BEFORE the cursor
    in the ordering is missed until the next read from the top."""
    base = _closed(_id(5), T0 + timedelta(minutes=5)) + _closed(_id(4), T0 + timedelta(minutes=4))
    first = await ReadStrategyTrades(FakeFillsSource(base)).read(S1, POOL, limit=1)
    assert _ids(first) == [_id(5)]

    booked = base + _closed(_id(1), T0 + timedelta(minutes=1))
    second = await ReadStrategyTrades(FakeFillsSource(booked)).read(
        S1, POOL, limit=5, before=first.next_cursor
    )

    assert _ids(second) == [_id(4), _id(1)]


async def test_only_this_strategys_closed_trades_are_listed() -> None:
    groups = (
        _closed(_id(1), T0)
        + _closed(_id(2), T0, strategy_id=S2)
        + [_group(S1, _id(3), "BUY", "100", symbol="STXUSDT.P", at=T0)]  # open, not a trade
    )

    page = await ReadStrategyTrades(FakeFillsSource(groups)).read(S1, POOL)

    assert _ids(page) == [_id(1)]


async def test_a_row_from_another_pool_is_refused_not_listed() -> None:
    groups = _closed(_id(1), T0) + _closed(_id(2), T0, exchange="binance")

    with pytest.raises(InvariantViolation):
        await ReadStrategyTrades(FakeFillsSource(groups)).read(S1, POOL)


async def test_an_item_carries_the_return_on_pool_capital_at_open_or_none() -> None:
    groups = (
        _closed(_id(1), T0 + timedelta(minutes=1), pnl="20", capital="1000")
        + _closed(_id(2), T0, pnl="7", capital=None)
    )

    page = await ReadStrategyTrades(FakeFillsSource(groups)).read(S1, POOL)

    first, second = page.trades
    assert (first.trade.pair, first.trade.pnl, first.value) == (
        "STXUSDT",
        Decimal("20"),
        Decimal("0.02"),
    )
    assert (second.trade.pnl, second.trade.pool_total_at_open, second.value) == (
        Decimal("7"),
        None,
        None,
    )
    assert first.trade.fees_complete is True


async def test_no_trades_returns_an_empty_page_not_an_error() -> None:
    empty = await ReadStrategyTrades(FakeFillsSource([])).read(S1, POOL)
    rehearsal_only = await ReadStrategyTrades(
        FakeFillsSource([], rehearsal_fill_count=3, rehearsal_by_strategy={S1: 3})
    ).read(S1, POOL)

    assert empty == TradesPage((), None)
    assert rehearsal_only == TradesPage((), None)


@pytest.mark.parametrize("limit", [0, -1, MAX_PAGE_SIZE + 1])
async def test_a_page_size_outside_the_bounds_is_refused(limit: int) -> None:
    reader = ReadStrategyTrades(FakeFillsSource(_closed(_id(1), T0)))

    with pytest.raises(InvalidPageRequest):
        await reader.read(S1, POOL, limit=limit)


async def test_the_default_and_maximum_page_sizes_are_accepted() -> None:
    reader = ReadStrategyTrades(FakeFillsSource(_closed(_id(1), T0)))

    assert len((await reader.read(S1, POOL)).trades) == 1
    assert len((await reader.read(S1, POOL, limit=MAX_PAGE_SIZE)).trades) == 1
    assert 1 <= DEFAULT_PAGE_SIZE <= MAX_PAGE_SIZE


def test_a_cursor_without_a_time_zone_is_refused() -> None:
    """A naive instant cannot be ordered against ``timestamptz`` values without
    guessing the zone it was written in."""
    with pytest.raises(InvalidPageRequest):
        TradeCursor(closed_at=datetime(2026, 9, 21, 12, 0), allocation_id=_id(1))


async def test_a_cursor_survives_a_round_trip_through_its_wire_form() -> None:
    """The cursor travels as two query parameters: the ISO-8601 instant with
    its full microseconds and the UUID text. Rebuilt from those strings it
    resumes at exactly the same place."""
    groups = _closed(_id(1), T0) + _closed(_id(2), T0) + _closed(_id(3), T0)
    reader = ReadStrategyTrades(FakeFillsSource(groups))
    first = await reader.read(S1, POOL, limit=1)
    assert first.next_cursor is not None

    rebuilt = TradeCursor(
        closed_at=datetime.fromisoformat(first.next_cursor.closed_at.isoformat()),
        allocation_id=UUID(str(first.next_cursor.allocation_id)),
    )
    second = await reader.read(S1, POOL, limit=10, before=rebuilt)

    assert _ids(second) == [_id(2), _id(1)]


async def test_an_unresolvable_symbol_is_a_warning_and_a_clean_page_is_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await ReadStrategyTrades(FakeFillsSource(_closed(_id(1), T0))).read(S1, POOL)
    assert caplog.records == []

    bad = _id(99)
    groups = _closed(_id(1), T0) + [_group(S1, bad, "BUY", "1", symbol="BTCEUR", at=T0)]
    with caplog.at_level(logging.INFO, logger=LOGGER):
        page = await ReadStrategyTrades(FakeFillsSource(groups)).read(S1, POOL)

    assert _ids(page) == [_id(1)]
    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert str(bad) in caplog.records[0].getMessage()


# --- rehearsal operations, on request (design addendum "a strategy's operations",
# sections C and E; tasks 9p.4.15 and 9p.4.16) ---------------------------------


def _rehearsal_closed(
    allocation_id: UUID,
    closed_at: datetime,
    *,
    strategy_id: UUID = S1,
    pnl: str = "0",
    capital: str | None = "1000",
) -> list[FillGroup]:
    """A closed round trip written by the simulated exchange. Opened as Pionex's
    ``STXUSDT_PERP`` and closed as TradingView's ``STXUSDT.P``."""
    opened = closed_at - timedelta(hours=1)
    return [
        replace(
            _group(
                strategy_id, allocation_id, "BUY", "100",
                symbol="STXUSDT_PERP", at=opened, capital=capital,
            ),
            rehearsal=True,
        ),
        replace(
            _group(
                strategy_id, allocation_id, "SELL", str(Decimal("100") + Decimal(pnl)),
                symbol="STXUSDT.P", at=closed_at, capital=capital,
            ),
            rehearsal=True,
        ),
    ]


def _flags(page: TradesPage) -> list[bool]:
    return [item.rehearsal for item in page.trades]


async def test_include_rehearsal_lists_the_closed_rehearsal_operations_marked() -> None:
    source = FakeFillsSource(
        _closed(_id(1), T0),
        rehearsal_groups=_rehearsal_closed(_id(2), T0 + timedelta(minutes=1)),
    )

    page = await ReadStrategyTrades(source).read(S1, POOL, include_rehearsal=True)

    assert len(page.trades) == 2
    assert _ids(page) == [_id(2), _id(1)]
    assert _flags(page) == [True, False]
    assert [item.trade.pair for item in page.trades] == ["STXUSDT", "STXUSDT"]


async def test_a_rehearsal_only_strategy_lists_its_operations() -> None:
    source = FakeFillsSource(
        [],
        rehearsal_fill_count=4,
        rehearsal_by_strategy={S1: 4},
        rehearsal_groups=_rehearsal_closed(_id(1), T0) + _rehearsal_closed(_id(2), T0),
    )

    page = await ReadStrategyTrades(source).read(S1, POOL, include_rehearsal=True)

    assert _ids(page) == [_id(2), _id(1)]
    assert _flags(page) == [True, True]


async def test_the_default_request_serves_no_rehearsal_row() -> None:
    source = FakeFillsSource(
        _closed(_id(1), T0),
        rehearsal_groups=_rehearsal_closed(_id(2), T0 + timedelta(minutes=1)),
    )
    reader = ReadStrategyTrades(source)

    default = await reader.read(S1, POOL)
    explicit_off = await reader.read(S1, POOL, include_rehearsal=False)

    assert _ids(default) == [_id(1)]
    assert _flags(default) == [False]
    assert default == explicit_off


async def test_a_mixed_allocation_is_listed_once_from_its_real_fills_and_one_warning_names_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mixed = _id(5)
    source = FakeFillsSource(
        _closed(mixed, T0) + _closed(_id(1), T0 - timedelta(hours=3)),
        rehearsal_groups=_rehearsal_closed(mixed, T0 + timedelta(hours=2))
        + _rehearsal_closed(_id(2), T0 - timedelta(hours=2)),
    )

    with caplog.at_level(logging.INFO, logger=LOGGER):
        page = await ReadStrategyTrades(source).read(S1, POOL, include_rehearsal=True)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "bybit/usdt-m/USDT" in message
    assert str(S1) in message
    assert str(mixed) in message
    assert str(_id(2)) not in message
    assert _ids(page) == [mixed, _id(2), _id(1)]
    assert _flags(page) == [False, True, False]
    assert page.trades[0].trade.closed_at == T0


async def test_a_real_and_a_rehearsal_operation_closing_at_the_same_instant_straddle_a_page_edge_and_each_is_served_once() -> (  # noqa: E501
    None
):
    """Two operations close at the same instant and the page size is one, so the
    page edge falls between them: the higher allocation id first, whichever kind
    it is. Each is served exactly once."""
    source = FakeFillsSource(
        _closed(_id(1), T0),
        rehearsal_groups=_rehearsal_closed(_id(2), T0),
    )
    reader = ReadStrategyTrades(source)

    first = await reader.read(S1, POOL, limit=1, include_rehearsal=True)
    assert first.next_cursor is not None
    second = await reader.read(
        S1, POOL, limit=1, before=first.next_cursor, include_rehearsal=True
    )

    assert (_ids(first), _flags(first)) == ([_id(2)], [True])
    assert (_ids(second), _flags(second)) == ([_id(1)], [False])
    assert second.next_cursor is None


async def test_a_cursor_minted_without_rehearsal_rows_resumes_correctly_with_them() -> None:
    """The cursor is a position in one total order, so a cursor minted by a
    request that did not ask for rehearsal rows resumes the list that does: the
    rehearsal operation newer than it is not repeated, the older one is served."""
    real = _closed(_id(1), T0 + timedelta(hours=2)) + _closed(_id(2), T0)
    rehearsal = _rehearsal_closed(_id(3), T0 + timedelta(hours=5)) + _rehearsal_closed(
        _id(4), T0 + timedelta(hours=1)
    )
    reader = ReadStrategyTrades(FakeFillsSource(real, rehearsal_groups=rehearsal))

    minted = await reader.read(S1, POOL, limit=1)
    assert minted.next_cursor is not None
    resumed = await reader.read(S1, POOL, before=minted.next_cursor, include_rehearsal=True)

    assert _ids(minted) == [_id(1)]
    assert _ids(resumed) == [_id(4), _id(2)]
    assert _flags(resumed) == [True, False]


async def test_a_rehearsal_operation_still_open_is_not_listed() -> None:
    open_rehearsal = [
        replace(
            _group(S1, _id(7), "BUY", "100", symbol="STXUSDT_PERP", at=T0),
            rehearsal=True,
        )
    ]
    source = FakeFillsSource(
        [],
        rehearsal_groups=open_rehearsal + _rehearsal_closed(_id(8), T0 - timedelta(hours=1)),
    )

    page = await ReadStrategyTrades(source).read(S1, POOL, include_rehearsal=True)

    assert _ids(page) == [_id(8)]


async def test_a_rehearsal_row_with_a_non_positive_pool_capital_is_refused_like_a_real_one() -> (
    None
):
    real = FakeFillsSource(_closed(_id(1), T0, capital="0"))
    rehearsal = FakeFillsSource(
        [], rehearsal_groups=_rehearsal_closed(_id(1), T0, capital="0")
    )
    caught: list[type[BaseException] | None] = []
    for source in (real, rehearsal):
        try:
            await ReadStrategyTrades(source).read(S1, POOL, include_rehearsal=True)
            caught.append(None)
        except InvariantViolation:
            caught.append(InvariantViolation)

    assert caught == [InvariantViolation, InvariantViolation]

"""Unit tests: the compounded return curve, drawdown, monthly grid and range
summaries (design.md section 11, decisions 12, 16 and 17; spec:
performance-reporting).

Pure ``Decimal`` domain, no I/O. Every expected figure is an exact ``Decimal``:
``Decimal("1.05") * Decimal("1.02")`` is exactly ``1.0710`` and the
assertions below are equality, never ``approx``.

Each trade's return is ``pnl / pool_total_at_open``; inside a UTC day, trades
that overlap are SUMMED and trades that follow each other COMPOUND (decision
40); days are COMPOUNDED. Nothing here reads a time zone from a
database session: the day of a trade is ``closed_at.astimezone(UTC).date()``.
"""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.closed_trade import ClosedTrade, Direction
from strategy_manager.performance.domain.curve import (
    DailyReturn,
    RangeName,
    build_pool_performance,
    compound,
    daily_returns,
    drawdowns,
    monthly_grid,
    range_summary,
)
from strategy_manager.performance.domain.derive_trade import DerivedTrades
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
UTC_MINUS_3 = timezone(timedelta(hours=-3))


def _trade(
    pnl: str,
    closed_at: datetime,
    *,
    capital: str | None = "1000",
    fees_complete: bool = True,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    opened_at: datetime | None = None,
) -> ClosedTrade:
    return ClosedTrade(
        allocation_id=uuid4(),
        strategy_id=uuid4(),
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        pair="SOLUSDT",
        direction=Direction.LONG,
        opened_at=closed_at - timedelta(hours=1) if opened_at is None else opened_at,
        closed_at=closed_at,
        pnl=Decimal(pnl),
        fees_complete=fees_complete,
        pool_total_at_open=None if capital is None else Decimal(capital),
    )


def _derived(*trades: ClosedTrade, open_trade_count: int = 0) -> DerivedTrades:
    return DerivedTrades(
        closed=tuple(trades), open_trade_count=open_trade_count, unresolved_allocation_ids=()
    )


def day(n: int) -> datetime:
    """Noon UTC on September ``n``, 2026."""
    return datetime(2026, 9, n, 12, 0, tzinfo=UTC)


def test_two_trades_different_days_compound_1_05_times_1_02() -> None:
    """The design's worked example: +5% on one UTC day, +2% on the next,
    index 1.05 * 1.02, chained."""
    trades = [_trade("50", day(1)), _trade("20", day(2))]

    points = compound(daily_returns(trades))

    assert [p.index for p in points] == [Decimal("1.05"), Decimal("1.05") * Decimal("1.02")]
    assert points[-1].index == Decimal("1.0710")
    assert [p.day for p in points] == [date(2026, 9, 1), date(2026, 9, 2)]


def test_two_trades_same_utc_day_summed_not_chained_0_03_index_1_03() -> None:
    """A 1,000 USDT pool: A (+20) and B (+10) both close on day 1. The pool
    made 30 on 1,000 = 3%, so the index is 1.03 -- NOT 1.02 * 1.01 = 1.0302,
    which would compound B on capital A's gain never reached (decision 12)."""
    trades = [_trade("20", day(1)), _trade("10", day(1))]

    points = compound(daily_returns(trades))

    assert len(points) == 1
    assert points[0].daily_return == Decimal("0.03")
    assert points[0].index == Decimal("1.03")
    assert points[0].index != Decimal("1.0302")


def test_same_day_returns_are_measured_against_each_trades_own_capital() -> None:
    """Triangulates the summing: A is +20 on 1,000 (0.02) and B +10 on 2,000
    (0.005). The day is 0.025, not a pnl total over one capital."""
    trades = [_trade("20", day(1), capital="1000"), _trade("10", day(1), capital="2000")]

    points = compound(daily_returns(trades))

    assert points[0].daily_return == Decimal("0.025")
    assert points[0].index == Decimal("1.025")


def _hour(hours: float) -> datetime:
    """``hours`` after midnight UTC on September 1, 2026 (negative: the day before)."""
    return datetime(2026, 9, 1, tzinfo=UTC) + timedelta(hours=hours)


def _between(pnl: str, opened: float, closed: float, capital: str = "1000") -> ClosedTrade:
    return _trade(pnl, _hour(closed), capital=capital, opened_at=_hour(opened))


def test_a_trade_opened_after_another_closed_that_day_compounds_on_it() -> None:
    """Decision 40: +3 % on 1,000, then +3 % on the 1,030 it left. The pool grew
    6.09 %, which the sum of decision 17 read as 6 %."""
    trades = [_between("30", 1, 2), _between("30.9", 3, 4, capital="1030")]

    assert daily_returns(trades) == (DailyReturn(date(2026, 9, 1), Decimal("0.0609")),)


def test_a_trade_opened_the_moment_another_closed_compounds_on_it() -> None:
    trades = [_between("30", 1, 2), _between("30.9", 2, 3, capital="1030")]

    assert daily_returns(trades) == (DailyReturn(date(2026, 9, 1), Decimal("0.0609")),)


def test_trades_that_overlap_are_one_group_that_a_later_trade_compounds_on() -> None:
    """A and B overlap (+2 % and +1 %); C opens after both closed (+10 / 1,030),
    whatever order the trades arrive in."""
    trades = [_between("10", 4, 5, capital="1030"), _between("20", 1, 3), _between("10", 2, 3.5)]

    assert daily_returns(trades) == (
        DailyReturn(date(2026, 9, 1), Decimal("1.03") * (1 + Decimal("10") / Decimal("1030")) - 1),
    )


def test_a_group_lasts_until_its_last_member_closes() -> None:
    """A (1-3) and B (2-6) overlap; C (4-5) overlaps only B, still open, so all
    three were sized against the same capital and are summed."""
    trades = [_between("10", 1, 3), _between("10", 2, 6), _between("10", 4, 5)]

    assert daily_returns(trades) == (DailyReturn(date(2026, 9, 1), Decimal("0.03")),)


def test_a_trade_opened_the_day_before_groups_by_when_it_was_open() -> None:
    """Opened at 22:00 the day before, closed at 01:00; the next opens at 02:00.
    Both close on September 1, one after the other."""
    trades = [_between("30", -2, 1), _between("30.9", 2, 3, capital="1030")]

    assert daily_returns(trades) == (DailyReturn(date(2026, 9, 1), Decimal("0.0609")),)


def test_two_groups_past_minus_100_percent_never_multiply_into_a_gain() -> None:
    """Decision 31 inside a day: -150 % and then -150 % would read +125 % if the
    groups' factors were multiplied unfloored."""
    trades = [_between("-1500", 1, 2), _between("-1500", 3, 4)]

    assert daily_returns(trades) == (DailyReturn(date(2026, 9, 1), Decimal("-1")),)


def test_design_worked_example_second_day_loss_compounds_on_the_first() -> None:
    """Day 2: C = 1030, -20.6 -> r = -0.02, E2 = 1.03 * 0.98 = 1.0094."""
    trades = [
        _trade("20", day(1), capital="1000"),
        _trade("10", day(1), capital="1000"),
        _trade("-20.6", day(2), capital="1030"),
    ]

    points = compound(daily_returns(trades))
    dd = drawdowns(points)

    assert [p.index for p in points] == [Decimal("1.03"), Decimal("1.0094")]
    assert dd[1] == Decimal("-0.02")


def test_drawdown_from_previous_peak_1_20_to_1_14_is_5_percent() -> None:
    """Peak 1.20, then 1.14: 1.14 / 1.20 - 1 = -5%."""
    trades = [_trade("200", day(1), capital="1000"), _trade("-60", day(2), capital="1200")]

    points = compound(daily_returns(trades))
    dd = drawdowns(points)

    assert [p.index for p in points] == [Decimal("1.2"), Decimal("1.14")]
    assert dd == (Decimal("0"), Decimal("-0.05"))


def test_no_drawdown_at_new_peak_is_zero() -> None:
    """Peak 1.20, dip to 1.14, then a new all-time high 1.254: drawdown is
    0 at both peaks and negative only in between."""
    trades = [
        _trade("200", day(1), capital="1000"),
        _trade("-60", day(2), capital="1200"),
        _trade("114", day(3), capital="1140"),
    ]

    dd = drawdowns(compound(daily_returns(trades)))

    assert dd == (Decimal("0"), Decimal("-0.05"), Decimal("0"))


def test_drawdown_measures_a_first_day_loss_against_the_starting_index_of_one() -> None:
    """E0 = 1 is the first peak. A pool that loses 2% on its first day is 2%
    below where it started, not at a drawdown of zero for lack of a peak."""
    dd = drawdowns(compound(daily_returns([_trade("-20", day(1))])))

    assert dd == (Decimal("-0.02"),)


def test_utc_month_boundary_close_at_2026_08_31_22_30_minus_3_counts_september() -> None:
    """Decision 16. 22:30 at UTC-3 is 01:30 UTC on 1 September: September.
    Triangulated on both sides of the boundary, whose legs are written in a
    zone other than UTC on purpose."""
    late_local = datetime(2026, 8, 31, 22, 30, tzinfo=UTC_MINUS_3)
    last_minute_of_august = datetime(2026, 8, 31, 20, 59, tzinfo=UTC_MINUS_3)  # 23:59 UTC
    exactly_midnight_utc = datetime(2026, 8, 31, 21, 0, tzinfo=UTC_MINUS_3)  # 00:00 UTC
    assert last_minute_of_august.astimezone(UTC).month == 8
    assert exactly_midnight_utc.astimezone(UTC).month == 9

    september = monthly_grid(compound(daily_returns([_trade("10", late_local)])))
    boundary = monthly_grid(
        compound(
            daily_returns(
                [_trade("10", last_minute_of_august), _trade("20", exactly_midnight_utc)]
            )
        )
    )

    assert [(m.year, m.month) for m in september] == [(2026, 9)]
    assert september[0].value == Decimal("0.01")
    assert [(m.year, m.month) for m in boundary] == [(2026, 8), (2026, 9)]
    assert [m.value for m in boundary] == [Decimal("0.01"), Decimal("0.02")]


def test_the_utc_day_of_a_local_close_is_the_utc_date_not_the_local_one() -> None:
    late_local = datetime(2026, 8, 31, 22, 30, tzinfo=UTC_MINUS_3)

    returns = daily_returns([_trade("10", late_local)])

    assert [r.day for r in returns] == [date(2026, 9, 1)]


def test_a_naive_close_time_is_refused_rather_than_read_in_the_hosts_zone() -> None:
    """``astimezone`` on a naive datetime silently assumes the machine's local
    zone, which is exactly the session-time-zone dependence decision 16
    forbids."""
    naive = ClosedTrade(
        allocation_id=uuid4(),
        strategy_id=uuid4(),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        pair="SOLUSDT",
        direction=Direction.LONG,
        opened_at=datetime(2026, 9, 1, 10, 0),
        closed_at=datetime(2026, 9, 1, 11, 0),
        pnl=Decimal("1"),
        fees_complete=True,
        pool_total_at_open=Decimal("1000"),
    )

    with pytest.raises(InvariantViolation):
        daily_returns([naive])


def test_monthly_return_chains_days_inside_the_month_and_measures_against_prior_month() -> None:
    """M = E(end of month) / E(end of previous month) - 1. August ends at
    1.10; September's days take it to 1.10 * 1.05 * 0.98 = 1.1319, so
    September is 1.1319 / 1.10 - 1 = 0.029, not the sum 0.05 - 0.02."""
    trades = [
        _trade("100", datetime(2026, 8, 20, 12, 0, tzinfo=UTC), capital="1000"),
        _trade("55", datetime(2026, 9, 1, 12, 0, tzinfo=UTC), capital="1100"),
        _trade("-23.1", datetime(2026, 9, 2, 12, 0, tzinfo=UTC), capital="1155"),
    ]

    grid = monthly_grid(compound(daily_returns(trades)))

    assert [(m.year, m.month) for m in grid] == [(2026, 8), (2026, 9)]
    assert grid[0].value == Decimal("0.1")
    assert grid[1].value == Decimal("0.029")


def test_exclusions_reported_two_open_one_missing_capital_at_open() -> None:
    """Spec scenario: two open trades and one closed trade without capital at
    open. The response reports both counts. The no-capital trade still counts
    in PnL amounts (no return can be computed for it) but never reaches the
    curve."""
    with_capital = _trade("20", day(1), capital="1000")
    no_capital = _trade("7", day(2), capital=None)

    report = build_pool_performance(
        POOL, _derived(with_capital, no_capital, open_trade_count=2), 0, NOW
    )

    assert report.exclusions.open_trade_count == 2
    assert report.exclusions.no_capital_at_open == 1
    assert [p.index for p in report.curve] == [Decimal("1.02")]
    assert report.closed_trade_count == 2
    assert report.total_pnl == Decimal("27")


def test_an_unconverted_fee_trade_stays_in_the_curve_and_is_counted() -> None:
    incomplete = _trade("20", day(1), fees_complete=False)
    complete = _trade("10", day(2))

    report = build_pool_performance(POOL, _derived(incomplete, complete), 0, NOW)

    assert report.exclusions.unconverted_fee == 1
    assert report.exclusions.no_capital_at_open == 0
    assert [p.index for p in report.curve] == [Decimal("1.02"), Decimal("1.02") * Decimal("1.01")]


def test_range_summary_7d_30d_90d_1y_all_computed_independently() -> None:
    """Trades at 3, 20, 60, 200 and 500 days before NOW. Each range is built
    from the trades inside ITS window, so 30D holds the trades of 7D plus the
    one at 20 days, and All holds everything. A range sliced out of the
    all-time curve would not reproduce these compounded figures."""
    trades = [
        _trade("10", NOW - timedelta(days=3)),
        _trade("20", NOW - timedelta(days=20)),
        _trade("30", NOW - timedelta(days=60)),
        _trade("40", NOW - timedelta(days=200)),
        _trade("50", NOW - timedelta(days=500)),
    ]

    by_range = {r.range: r for r in range_summary(trades, NOW)}

    assert list(by_range) == [
        RangeName.D7,
        RangeName.D30,
        RangeName.D90,
        RangeName.Y1,
        RangeName.ALL,
    ]
    assert [by_range[r].pnl for r in by_range] == [
        Decimal("10"),
        Decimal("30"),
        Decimal("60"),
        Decimal("100"),
        Decimal("150"),
    ]
    assert [by_range[r].trade_count for r in by_range] == [1, 2, 3, 4, 5]
    assert by_range[RangeName.D7].value == Decimal("0.01")
    assert by_range[RangeName.D30].value == Decimal("1.01") * Decimal("1.02") - 1
    assert by_range[RangeName.ALL].value == (
        Decimal("1.01") * Decimal("1.02") * Decimal("1.03") * Decimal("1.04") * Decimal("1.05")
        - 1
    )


def test_range_window_includes_its_start_instant_and_excludes_one_second_before() -> None:
    inside = _trade("10", NOW - timedelta(days=7))
    outside = _trade("99", NOW - timedelta(days=7, seconds=1))

    seven_day = range_summary([inside, outside], NOW)[0]

    assert seven_day.range is RangeName.D7
    assert seven_day.pnl == Decimal("10")
    assert seven_day.trade_count == 1


def test_a_range_counts_a_no_capital_trade_in_pnl_but_not_in_its_return() -> None:
    with_capital = _trade("10", NOW - timedelta(days=1))
    no_capital = _trade("5", NOW - timedelta(days=2), capital=None)

    seven_day = range_summary([with_capital, no_capital], NOW)[0]

    assert seven_day.pnl == Decimal("15")
    assert seven_day.trade_count == 2
    assert seven_day.value == Decimal("0.01")


def test_no_qualifying_trades_yields_empty_result_not_error() -> None:
    report = build_pool_performance(POOL, _derived(), 0, NOW)

    assert report.pool == POOL
    assert report.curve == ()
    assert report.monthly == ()
    assert report.closed_trade_count == 0
    assert report.total_pnl == Decimal("0")
    assert report.max_drawdown == Decimal("0")
    assert [(r.range, r.pnl, r.value, r.trade_count) for r in report.ranges] == [
        (name, Decimal("0"), Decimal("0"), 0) for name in RangeName
    ]
    assert report.exclusions.open_trade_count == 0


def test_only_rehearsal_fills_yields_same_empty_result() -> None:
    """A DRY_RUN ledger: the source returned no groups at all, and counted 12
    rehearsal fills it left out. The result equals the empty one in every
    figure; the only difference is that the exclusion count says why."""
    empty = build_pool_performance(POOL, _derived(), 0, NOW)

    rehearsal_only = build_pool_performance(POOL, _derived(), 12, NOW)

    assert rehearsal_only.exclusions.rehearsal_fill_count == 12
    assert rehearsal_only.curve == empty.curve == ()
    assert rehearsal_only.monthly == empty.monthly
    assert rehearsal_only.ranges == empty.ranges
    assert rehearsal_only.total_pnl == empty.total_pnl == Decimal("0")


def test_a_day_that_loses_exactly_everything_leaves_the_index_at_zero() -> None:
    points = compound(daily_returns([_trade("-1000", day(1))]))

    assert [p.index for p in points] == [Decimal("0")]


def test_a_day_past_minus_100_percent_stops_at_zero_and_keeps_its_own_sum() -> None:
    """A day's trades are summed, and the sum has no floor of its own: each trade
    reads against the whole capital, so twenty losers of 7% add up to -140%."""
    points = compound(daily_returns([_trade("-1400", day(1))]))

    assert points[0].daily_return == Decimal("-1.4")
    assert points[0].index == Decimal("0")


def test_two_days_past_minus_100_percent_never_multiply_into_a_gain() -> None:
    """Decision 31: -210% twice read as +21% before the floor."""
    points = compound(daily_returns([_trade("-2100", day(1)), _trade("-2100", day(2))]))

    assert [p.index for p in points] == [Decimal("0"), Decimal("0")]


def test_nothing_comes_back_after_the_index_reached_zero() -> None:
    trades = [_trade("-1400", day(1)), _trade("500", day(2)), _trade("-2100", day(3))]

    points = compound(daily_returns(trades))

    assert [p.index for p in points] == [Decimal("0"), Decimal("0"), Decimal("0")]
    assert not any(p.index.is_signed() for p in points)


def test_the_month_after_a_wipe_out_reads_zero_not_a_division_by_zero() -> None:
    october = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    points = compound(daily_returns([_trade("-1400", day(1)), _trade("500", october)]))

    grid = monthly_grid(points)

    assert [(m.year, m.month, m.value) for m in grid] == [
        (2026, 9, Decimal("-1")),
        (2026, 10, Decimal("0")),
    ]


def test_a_wipe_out_reads_minus_100_percent_in_every_figure_of_the_report() -> None:
    october = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    trades = [_trade("-1400", day(1)), _trade("500", day(2)), _trade("-2100", october)]

    report = build_pool_performance(POOL, _derived(*trades), 0, october)

    assert report.max_drawdown == Decimal("-1")
    assert [point.index for point in report.curve] == [Decimal("0")] * 3
    assert [month.value for month in report.monthly] == [Decimal("-1"), Decimal("0")]
    whole = next(r for r in report.ranges if r.range is RangeName.ALL)
    assert whole.value == Decimal("-1")


def test_max_drawdown_is_the_deepest_point_of_the_curve() -> None:
    trades = [
        _trade("200", day(1), capital="1000"),
        _trade("-60", day(2), capital="1200"),
        _trade("114", day(3), capital="1140"),
        _trade("-125.4", day(4), capital="1254"),
    ]

    report = build_pool_performance(POOL, _derived(*trades), 0, NOW)

    # day 4: 1.254 * 0.9 = 1.1286; peak 1.254 -> -10%
    assert report.max_drawdown == Decimal("-0.1")
    assert report.curve[-1].drawdown == Decimal("-0.1")


def test_trades_from_two_pools_are_refused_not_blended() -> None:
    """Rule 7. Two pools that both settle in USDT, on different exchanges. A
    curve over Bybit's pool that has one Binance trade in it would mix two
    pools' money into one number; it must raise instead."""
    bybit = _trade("20", day(1))
    binance = _trade("10", day(1), exchange="binance")

    with pytest.raises(InvariantViolation):
        build_pool_performance(POOL, _derived(bybit, binance), 0, NOW)


@pytest.mark.parametrize(
    "stray",
    [
        {"venue": "spot"},
        {"settlement_currency": "BTC"},
    ],
)
def test_a_trade_that_differs_from_the_pool_in_any_one_field_is_refused(
    stray: dict[str, str],
) -> None:
    with pytest.raises(InvariantViolation):
        build_pool_performance(POOL, _derived(_trade("20", day(1), **stray)), 0, NOW)

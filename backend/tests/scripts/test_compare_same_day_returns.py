"""The pure part of ``scripts/compare_same_day_returns.py``.

Decision 17 sums the returns of trades that close on one UTC day. That is exact
for trades that overlap, sized against the same capital, and misses ``r1 * r2``
for a trade opened after another closed, whose capital already held the first's
result. The script compares that curve with one that sums only overlapping
trades and compounds the groups that follow each other.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from compare_same_day_returns import compare, exact_daily_returns

from strategy_manager.performance.domain.closed_trade import ClosedTrade, Direction
from strategy_manager.performance.domain.curve import DailyReturn

DAY = datetime(2026, 10, 7, tzinfo=UTC)


def _trade(
    pnl: str, opened_hour: float, closed_hour: float, capital: str | None = "1000"
) -> ClosedTrade:
    return ClosedTrade(
        allocation_id=uuid4(),
        strategy_id=uuid4(),
        exchange="binance",
        venue="usdt-m",
        settlement_currency="USDT",
        pair="SOLUSDT",
        direction=Direction.LONG,
        opened_at=DAY + timedelta(hours=opened_hour),
        closed_at=DAY + timedelta(hours=closed_hour),
        pnl=Decimal(pnl),
        fees_complete=True,
        pool_total_at_open=None if capital is None else Decimal(capital),
    )


def test_trades_that_overlap_are_summed_as_decision_17_does() -> None:
    trades = [_trade("20", 1, 5), _trade("10", 2, 6)]

    assert exact_daily_returns(trades) == (DailyReturn(DAY.date(), Decimal("0.03")),)


def test_a_trade_opened_after_another_closed_is_compounded_on_it() -> None:
    """+3 % on 1,000, then +3 % on the 1,030 it left: the pool grew 6.09 %."""
    trades = [_trade("30", 1, 2), _trade("30.9", 3, 4, capital="1030")]

    assert exact_daily_returns(trades) == (DailyReturn(DAY.date(), Decimal("0.0609")),)


def test_overlapping_trades_are_one_group_that_a_later_trade_compounds_on() -> None:
    """A and B overlap (+2 % and +1 %); C opens after both closed (+10 %)."""
    trades = [_trade("10", 4, 5, capital="1030"), _trade("20", 1, 3), _trade("10", 2, 3.5)]

    assert exact_daily_returns(trades) == (
        DailyReturn(DAY.date(), Decimal("1.03") * (1 + Decimal("10") / Decimal("1030")) - 1),
    )


def test_a_group_lasts_until_its_last_member_closes() -> None:
    """A (1-3) and B (2-6) overlap; C (4-5) overlaps only B, still open, so all
    three were sized against the same capital and are summed."""
    trades = [_trade("10", 1, 3), _trade("10", 2, 6), _trade("10", 4, 5)]

    assert exact_daily_returns(trades) == (DailyReturn(DAY.date(), Decimal("0.03")),)


def test_a_trade_opened_the_day_before_still_groups_by_the_time_it_overlaps() -> None:
    """Opened at 22:00 the day before and closed at 01:00; the next opens at
    02:00. Both close on the same UTC day, one after the other."""
    trades = [_trade("30", -2, 1), _trade("30.9", 2, 3, capital="1030")]

    assert exact_daily_returns(trades) == (DailyReturn(DAY.date(), Decimal("0.0609")),)


def test_a_trade_opened_the_moment_another_closed_is_compounded_on_it() -> None:
    trades = [_trade("30", 1, 2), _trade("30.9", 2, 3, capital="1030")]

    assert exact_daily_returns(trades) == (DailyReturn(DAY.date(), Decimal("0.0609")),)


def test_a_trade_with_no_capital_at_open_has_no_return_and_is_left_out() -> None:
    trades = [_trade("30", 1, 2), _trade("99", 3, 4, capital=None)]

    assert exact_daily_returns(trades) == (DailyReturn(DAY.date(), Decimal("0.03")),)


def test_days_are_kept_apart_and_in_order() -> None:
    trades = [_trade("10", 25, 26), _trade("20", 1, 2)]

    assert [r.day for r in exact_daily_returns(trades)] == [
        DAY.date(),
        (DAY + timedelta(days=1)).date(),
    ]


def test_the_comparison_reads_both_end_indices_and_the_days_that_differ() -> None:
    trades = [_trade("30", 1, 2), _trade("30.9", 3, 4, capital="1030"), _trade("10", 26, 27)]

    result = compare(trades)

    assert result.trades == 3
    assert result.days == 2
    assert result.sequential_days == 1
    assert result.summed_end == Decimal("1.06") * Decimal("1.01")
    assert result.exact_end == Decimal("1.0609") * Decimal("1.01")
    assert result.largest_day_gap == Decimal("0.0009")

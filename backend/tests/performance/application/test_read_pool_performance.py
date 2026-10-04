"""Unit tests: ``ReadPoolPerformance``, the application read that composes the
domain functions over ``AllocationFillsSourcePort`` (tasks.md 3c.9).

The source is a fake; the domain is the real one. What is proven here is the
composition: one pool asked for, "now" from the clock port, the rule-7 refusal,
and that what the read leaves out is visible in the log as well as the report.

**Binding testing lesson**: a symbol has three spellings. The trade below is
opened as ``SOLUSDT.P`` and closed as ``SOLUSDT`` (a booked close).
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.read_pool_performance import ReadPoolPerformance
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.curve import RangeName
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.performance.fakes import FakeFillsSource, FixedClock

POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
LOGGER = "strategy_manager.performance.application.read_pool_performance"


def _group(
    allocation_id: UUID,
    side: str,
    notional: str,
    *,
    symbol: str = "SOLUSDT.P",
    at: datetime = NOW - timedelta(days=2),
    capital: str | None = "1000",
    fee_currency: str = "USDT",
    fee: str = "0",
    exchange: str = "bybit",
    venue: str = "usdt-m",
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=uuid4(),
        exchange=exchange,
        venue=venue,
        settlement_currency="USDT",
        symbol=symbol,
        side=side,
        fee_currency=fee_currency,
        quantity=Decimal("1"),
        notional=Decimal(notional),
        fee=Decimal(fee),
        first_filled_at=at,
        last_filled_at=at,
        pool_total_at_open=None if capital is None else Decimal(capital),
        rehearsal=False,
    )


def _closed_trade(pnl: str, *, capital: str | None = "1000", **kwargs: object) -> list[FillGroup]:
    a = uuid4()
    return [
        _group(a, "BUY", "100", capital=capital, **kwargs),  # type: ignore[arg-type]
        _group(
            a,
            "SELL",
            str(Decimal("100") + Decimal(pnl)),
            symbol="SOLUSDT",
            capital=capital,
            **kwargs,  # type: ignore[arg-type]
        ),
    ]


async def test_reads_one_pool_and_builds_the_report_with_now_from_the_clock() -> None:
    source = FakeFillsSource(_closed_trade("20") + _closed_trade("10"), rehearsal_fill_count=3)

    report = await ReadPoolPerformance(source, FixedClock(NOW)).read(POOL)

    assert source.asked == [POOL]
    assert report.pool == POOL
    assert [p.index for p in report.curve] == [Decimal("1.03")]
    assert report.closed_trade_count == 2
    assert report.exclusions.rehearsal_fill_count == 3
    assert {r.range: r.pnl for r in report.ranges}[RangeName.D7] == Decimal("30")


async def test_now_comes_from_the_clock_port_not_the_wall_clock() -> None:
    """The same ledger read 100 days later: the trade has left the 7D and 30D
    windows. Only an injected clock can make that observable."""
    groups = _closed_trade("20")

    early = await ReadPoolPerformance(FakeFillsSource(groups), FixedClock(NOW)).read(POOL)
    late = await ReadPoolPerformance(
        FakeFillsSource(groups), FixedClock(NOW + timedelta(days=100))
    ).read(POOL)

    early_ranges = {r.range: r.trade_count for r in early.ranges}
    late_ranges = {r.range: r.trade_count for r in late.ranges}
    assert early_ranges[RangeName.D7] == 1
    assert late_ranges[RangeName.D7] == 0
    assert late_ranges[RangeName.D90] == 0
    assert late_ranges[RangeName.Y1] == 1


async def test_a_source_that_returns_another_pools_rows_is_refused() -> None:
    """Rule 7. A misbehaving source hands back a Binance trade for a Bybit
    read. Its rows are for a pool nobody asked about; they must raise, not be
    folded into the curve."""
    source = FakeFillsSource(_closed_trade("20") + _closed_trade("10", exchange="binance"))

    with pytest.raises(InvariantViolation):
        await ReadPoolPerformance(source, FixedClock(NOW)).read(POOL)


async def test_a_stray_row_is_refused_even_when_it_would_only_count_as_open() -> None:
    """The pool check is on the ROWS, not only on finished trades: a lone
    opening leg from another venue would otherwise be counted as an open
    trade of this pool, silently."""
    stray_open = [_group(uuid4(), "BUY", "100", venue="spot")]
    source = FakeFillsSource(_closed_trade("20") + stray_open)

    with pytest.raises(InvariantViolation):
        await ReadPoolPerformance(source, FixedClock(NOW)).read(POOL)


async def test_two_pools_read_through_the_same_use_case_never_share_a_figure() -> None:
    """Two separate reads, two separate reports: nothing is cached or summed
    on the use case between calls."""
    other = PoolKey(Exchange.BINANCE, Venue.USDT_M, Currency.USDT)
    bybit_source = FakeFillsSource(_closed_trade("20"))
    binance_source = FakeFillsSource(_closed_trade("50", exchange="binance"))

    bybit = await ReadPoolPerformance(bybit_source, FixedClock(NOW)).read(POOL)
    binance = await ReadPoolPerformance(binance_source, FixedClock(NOW)).read(other)

    assert bybit.total_pnl == Decimal("20")
    assert binance.total_pnl == Decimal("50")
    assert bybit.pool != binance.pool


async def test_a_pre_0026_reservation_is_reported_as_excluded_and_the_curve_still_works() -> None:
    """Production holds two reservations from before migration 0026. They must
    show up in PnL amounts and in the exclusion count, and the curve for the
    rest must not break."""
    source = FakeFillsSource(
        _closed_trade("20") + _closed_trade("7", capital=None) + _closed_trade("5", capital=None)
    )

    report = await ReadPoolPerformance(source, FixedClock(NOW)).read(POOL)

    assert report.exclusions.no_capital_at_open == 2
    assert [p.index for p in report.curve] == [Decimal("1.02")]
    assert report.total_pnl == Decimal("32")


async def test_an_allocation_with_no_base_currency_is_logged_as_a_warning_with_its_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bad = uuid4()
    source = FakeFillsSource(_closed_trade("20") + [_group(bad, "BUY", "1", symbol="BTCEUR")])

    with caplog.at_level(logging.INFO, logger=LOGGER):
        report = await ReadPoolPerformance(source, FixedClock(NOW)).read(POOL)

    assert report.exclusions.unresolved_allocation_count == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(bad) in warnings[0].getMessage()


async def test_missing_capital_and_unconverted_fees_are_logged_at_info_with_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = FakeFillsSource(
        _closed_trade("7", capital=None)
        + _closed_trade("5", fee_currency="BNB", fee="0.01"),
    )

    with caplog.at_level(logging.INFO, logger=LOGGER):
        await ReadPoolPerformance(source, FixedClock(NOW)).read(POOL)

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("no capital at open" in m and "1" in m for m in messages)
    assert any("unconverted fee" in m and "1" in m for m in messages)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


async def test_a_clean_pool_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await ReadPoolPerformance(FakeFillsSource(_closed_trade("20")), FixedClock(NOW)).read(POOL)

    assert caplog.records == []


async def test_an_empty_ledger_returns_the_empty_result_not_an_error() -> None:
    report = await ReadPoolPerformance(FakeFillsSource([]), FixedClock(NOW)).read(POOL)

    assert report.curve == ()
    assert report.closed_trade_count == 0
    assert report.total_pnl == Decimal("0")

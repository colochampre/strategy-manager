"""Unit tests: ``ReadStrategyPerformance`` -- one strategy's curve, stats and
per-pair breakdown, composed over ``AllocationFillsSourcePort`` (tasks.md
3d.3).

The source is a fake; the domain is the real one. What is proven here is the
scoping: a strategy is exactly one strategy in exactly one pool (decision 1), a
strategy's figures are expressed in that pool's settlement currency alone
(CLAUDE.md rule 7), its return uses the POOL's capital at open as the
denominator (decision 17), and what it leaves out is visible in the report and
in the log.

**Binding testing lesson**: a symbol has three spellings. Every trade below is
opened as ``SOLUSDT.P`` and closed as ``SOLUSDT``.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.read_pool_performance import ReadPoolPerformance
from strategy_manager.performance.application.read_strategy_performance import (
    ReadStrategyPerformance,
)
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.performance.fakes import FakeFillsSource, FixedClock

POOL = PoolKey(Exchange.BYBIT, Venue.USDT_M, Currency.USDT)
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
DAY1 = NOW - timedelta(days=3)
DAY2 = NOW - timedelta(days=2)
LOGGER = "strategy_manager.performance.application.read_strategy_performance"
S1 = uuid4()
S2 = uuid4()


def _group(
    strategy_id: UUID,
    allocation_id: UUID,
    side: str,
    notional: str,
    *,
    symbol: str = "SOLUSDT.P",
    at: datetime = DAY1,
    capital: str | None = "1000",
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement: str = "USDT",
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=strategy_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement,
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
    strategy_id: UUID,
    pnl: str,
    *,
    at: datetime = DAY1,
    capital: str | None = "1000",
    pair: str = "SOLUSDT",
) -> list[FillGroup]:
    a = uuid4()
    return [
        _group(strategy_id, a, "BUY", "100", symbol=f"{pair}.P", at=at, capital=capital),
        _group(
            strategy_id,
            a,
            "SELL",
            str(Decimal("100") + Decimal(pnl)),
            symbol=pair,
            at=at,
            capital=capital,
        ),
    ]


def _read(source: FakeFillsSource, strategy_id: UUID = S1):  # type: ignore[no-untyped-def]
    return ReadStrategyPerformance(source, FixedClock(NOW)).read(strategy_id, POOL)


async def test_strategy_curve_uses_pool_capital_at_open_as_contribution() -> None:
    """S1 makes +20 and S2 makes +10, both on a 1000 pool the day they close.
    S1's return is 20/1000 = 2% (its CONTRIBUTION to the pool), not 20 over
    whatever S1 alone might have held. The next day S1 loses 10.3 on a pool
    that had grown to 1030: -1%. Chained: 1.02 * 0.99. And the strategies'
    daily contributions add up to the pool's own daily return."""
    groups = (
        _closed(S1, "20", at=DAY1)
        + _closed(S1, "-10.3", at=DAY2, capital="1030")
        + _closed(S2, "10", at=DAY1)
    )

    report = await _read(FakeFillsSource(groups))
    pool = await ReadPoolPerformance(FakeFillsSource(groups), FixedClock(NOW)).read(POOL)

    curve = report.performance.curve
    assert [p.daily_return for p in curve] == [Decimal("0.02"), Decimal("-0.01")]
    assert [p.index for p in curve] == [Decimal("1.02"), Decimal("1.02") * Decimal("0.99")]
    assert pool.curve[0].daily_return == curve[0].daily_return + Decimal("0.01")
    assert report.performance.total_pnl == Decimal("9.7")


async def test_strategy_stats_scoped_to_its_own_pool_settlement_currency() -> None:
    """The read asks the source for exactly the pool it was given, states the
    pool in the report, and leaves the other strategy's trades out."""
    source = FakeFillsSource(_closed(S1, "20") + _closed(S2, "50"))

    report = await _read(source)

    assert source.asked == [POOL]
    assert report.strategy_id == S1
    assert report.performance.pool == POOL
    assert report.performance.pool.settlement_currency is Currency.USDT
    assert report.performance.total_pnl == Decimal("20")
    assert report.performance.closed_trade_count == 1


@pytest.mark.parametrize(
    ("exchange", "venue", "settlement"),
    [
        ("binance", "usdt-m", "USDT"),  # same venue and currency, another exchange
        ("bybit", "spot", "USDT"),  # same exchange and currency, another venue
        ("bybit", "usdt-m", "BTC"),  # same exchange and venue, another currency
    ],
)
async def test_a_row_of_the_strategy_from_another_pool_is_refused(
    exchange: str, venue: str, settlement: str
) -> None:
    """Rule 7. A misbehaving source hands back S1's trade from a pool nobody
    asked about. It must raise, not be folded into S1's curve, even though the
    row carries S1's strategy id."""
    stray = _closed(S1, "20")
    stray = [
        _group(S1, g.allocation_id, g.side, str(g.notional), exchange=exchange, venue=venue,
               settlement=settlement)
        for g in stray
    ]
    source = FakeFillsSource(_closed(S1, "10") + stray)

    with pytest.raises(InvariantViolation):
        await _read(source)


async def test_a_stray_row_of_another_strategy_and_pool_is_refused_too() -> None:
    """The pool check runs on EVERY row the source returns, before the strategy
    filter, so a row that would have been dropped as 'someone else's' still
    proves the source misbehaved."""
    other_pool_row = _group(S2, uuid4(), "BUY", "100", exchange="binance")
    source = FakeFillsSource(_closed(S1, "10") + [other_pool_row])

    with pytest.raises(InvariantViolation):
        await _read(source)


async def test_an_allocation_split_across_two_strategies_is_refused() -> None:
    """An allocation is one reservation of one strategy. If its legs come back
    under two strategy ids the ledger is inconsistent, and deriving either
    half would book a phantom open trade or a wrong PnL."""
    a = uuid4()
    split = [_group(S1, a, "BUY", "100"), _group(S2, a, "SELL", "110", symbol="SOLUSDT")]

    with pytest.raises(InvariantViolation):
        await _read(FakeFillsSource(split))


async def test_by_pair_merges_spellings_and_keeps_a_pair_that_is_no_longer_allowed() -> None:
    """Decision 15: the allowlist gates opens only. This read takes no
    allowlist, so a pair the strategy may no longer open still shows its
    history. SOLUSDT (open ``.P``, close bare) is one pair."""
    groups = (
        _closed(S1, "5", pair="SOLUSDT")
        + _closed(S1, "-2", pair="SOLUSDT", at=DAY2)
        + _closed(S1, "10", pair="BTCUSDT")
        + _closed(S2, "99", pair="ETHUSDT")
    )

    report = await _read(FakeFillsSource(groups))

    assert [(p.pair, p.trade_count, p.pnl) for p in report.by_pair] == [
        ("BTCUSDT", 1, Decimal("10")),
        ("SOLUSDT", 2, Decimal("3")),
    ]


async def test_exclusions_are_this_strategys_own() -> None:
    """Open allocations, rehearsal fills and missing capital are counted for
    THIS strategy: S2's open position and S2's rehearsal fills are not S1's."""
    s1_open = [_group(S1, uuid4(), "BUY", "100")]
    s2_open = [_group(S2, uuid4(), "BUY", "100")]
    source = FakeFillsSource(
        _closed(S1, "20") + _closed(S1, "7", capital=None) + s1_open + s2_open + _closed(S2, "1"),
        rehearsal_fill_count=7,
        rehearsal_by_strategy={S1: 2, S2: 5},
    )

    report = await _read(source)

    ex = report.performance.exclusions
    assert ex.open_trade_count == 1
    assert ex.rehearsal_fill_count == 2
    assert ex.no_capital_at_open == 1
    assert report.performance.total_pnl == Decimal("27")
    assert [p.index for p in report.performance.curve] == [Decimal("1.02")]


async def test_a_strategy_with_no_trades_returns_the_empty_result_not_an_error() -> None:
    report = await _read(FakeFillsSource(_closed(S2, "20")))

    assert report.performance.curve == ()
    assert report.performance.closed_trade_count == 0
    assert report.performance.total_pnl == Decimal("0")
    assert report.by_pair == ()


async def test_a_strategy_with_only_rehearsal_fills_returns_the_same_empty_result() -> None:
    report = await _read(FakeFillsSource([], rehearsal_fill_count=4, rehearsal_by_strategy={S1: 4}))

    assert report.performance.curve == ()
    assert report.by_pair == ()
    assert report.performance.exclusions.rehearsal_fill_count == 4


async def test_an_unresolvable_symbol_is_a_warning_naming_only_this_strategys_allocation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bad, other = uuid4(), uuid4()
    source = FakeFillsSource(
        _closed(S1, "20")
        + [
            _group(S1, bad, "BUY", "1", symbol="BTCEUR"),
            _group(S2, other, "BUY", "1", symbol="BTCEUR"),
        ]
    )

    with caplog.at_level(logging.INFO, logger=LOGGER):
        report = await _read(source)

    assert report.performance.exclusions.unresolved_allocation_count == 1
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(bad) in warnings[0].getMessage()
    assert str(other) not in warnings[0].getMessage()
    assert str(S1) in warnings[0].getMessage()


async def test_missing_capital_is_info_and_a_clean_strategy_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await _read(FakeFillsSource(_closed(S1, "20")))
    assert caplog.records == []

    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        await _read(FakeFillsSource(_closed(S1, "7", capital=None)))
    assert [r.levelno for r in caplog.records] == [logging.INFO]
    assert "no capital at open" in caplog.records[0].getMessage()

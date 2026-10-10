"""Unit tests: ``by_pair`` -- a strategy's closed trades grouped per allocation
and then by ``market_key`` (design.md section 11; spec: performance-reporting
requirement "Stats By Strategy and By Pair"; tasks.md 3d.1-3d.2).

Pure ``Decimal`` domain, no I/O.

**Binding testing lesson**: a symbol has three spellings (TradingView
``SOLUSDT.P``, venue bare ``SOLUSDT``, Pionex ``SOLUSDT_PERP``). The legs of
one trade below are written under different spellings on purpose, and the pair
must come out as one.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.domain.by_pair import PairStats, by_pair
from strategy_manager.performance.domain.closed_trade import ClosedTrade, Direction, FillGroup
from strategy_manager.performance.domain.derive_trade import derive_trades

OPENED = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
CLOSED = datetime(2026, 9, 2, 11, 30, tzinfo=UTC)
STRATEGY = uuid4()


def _group(
    allocation_id: UUID, side: str, notional: str, symbol: str, *, at: datetime
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=STRATEGY,
        exchange="bybit",
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
        pool_total_at_open=Decimal("1000"),
        rehearsal=False,
    )


def _trade(
    pair: str, pnl: str, *, capital: str | None = "1000", closed_at: datetime = CLOSED
) -> ClosedTrade:
    return ClosedTrade(
        allocation_id=uuid4(),
        strategy_id=STRATEGY,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        pair=pair,
        direction=Direction.LONG,
        opened_at=OPENED,
        closed_at=closed_at,
        pnl=Decimal(pnl),
        fees_complete=True,
        pool_total_at_open=None if capital is None else Decimal(capital),
    )


def test_solusdt_dot_p_and_solusdt_merge_into_one_pair() -> None:
    """Spec: an allocation opened on ``SOLUSDT.P`` and closed by a booked fill
    written as ``SOLUSDT`` is ONE trade under ONE pair. A second allocation
    spelled ``SOLUSDT_PERP`` then ``solusdt`` joins it. Each leg wears a
    different spelling, taken through the real derivation."""
    a, b = uuid4(), uuid4()
    derived = derive_trades(
        [
            _group(a, "BUY", "100", "SOLUSDT.P", at=OPENED),
            _group(a, "SELL", "105", "SOLUSDT", at=CLOSED),
            _group(b, "BUY", "100", "SOLUSDT_PERP", at=OPENED),
            _group(b, "SELL", "103", "solusdt", at=CLOSED),
        ]
    )

    assert by_pair(derived.closed) == (
        PairStats(
            pair="SOLUSDT",
            trade_count=2,
            pnl=Decimal("8"),
            value=Decimal("0.008"),
            win_count=2,
            win_rate=Decimal(1),
        ),
    )


def test_trades_keyed_under_different_spellings_still_merge() -> None:
    """The function re-keys with ``market_key`` rather than trusting the
    caller's ``pair``: a trade built elsewhere with a raw spelling must not
    open a second row for the same market."""
    result = by_pair(
        [_trade("SOLUSDT.P", "5"), _trade("SOLUSDT_PERP", "3"), _trade("solusdt", "1")]
    )

    assert [(p.pair, p.trade_count, p.pnl) for p in result] == [("SOLUSDT", 3, Decimal("9"))]


def test_per_pair_stats_include_pair_removed_from_allowlist() -> None:
    """Allowlist independence (decision 15: the allowlist gates OPENS only).
    The strategy's allowlist today is BTCUSDT alone; SOLUSDT was removed after
    it traded. ``by_pair`` is given no allowlist at all, so SOLUSDT's history
    is there with its exact count and PnL."""
    allowed_today = {"BTCUSDT"}
    trades = [_trade("SOLUSDT", "5"), _trade("SOLUSDT", "-2"), _trade("BTCUSDT", "10")]

    result = {p.pair: p for p in by_pair(trades)}

    assert "SOLUSDT" not in allowed_today
    assert set(result) == {"BTCUSDT", "SOLUSDT"}
    assert result["SOLUSDT"].trade_count == 2
    assert result["SOLUSDT"].pnl == Decimal("3")
    assert result["BTCUSDT"].pnl == Decimal("10")


def test_each_pair_return_is_its_own_contribution_to_the_pool() -> None:
    """r_i = pnl_i / pool capital at open, summed within a UTC day and chained
    across days, per pair. SOL: +20 then -10 on 1000 (1.02 * 0.99 - 1);
    BTC: +10 on 1000."""
    day2 = datetime(2026, 9, 3, 11, 30, tzinfo=UTC)
    trades = [
        _trade("SOLUSDT", "20", closed_at=CLOSED),
        _trade("SOLUSDT", "-10", closed_at=day2),
        _trade("BTCUSDT", "10", closed_at=CLOSED),
    ]

    result = {p.pair: p for p in by_pair(trades)}

    assert result["SOLUSDT"].value == Decimal("1.02") * Decimal("0.99") - Decimal("1")
    assert result["BTCUSDT"].value == Decimal("0.01")


def test_trades_without_capital_count_in_pnl_but_have_no_return() -> None:
    """A pre-0026 trade has an amount and no return; a pair made only of them
    reports ``None``, never a fabricated zero."""
    result = {p.pair: p for p in by_pair([
        _trade("SOLUSDT", "7", capital=None),
        _trade("BTCUSDT", "5", capital=None),
        _trade("BTCUSDT", "5"),
    ])}

    assert result["SOLUSDT"] == PairStats("SOLUSDT", 1, Decimal("7"), None, 1, Decimal(1))
    assert result["BTCUSDT"].trade_count == 2
    assert result["BTCUSDT"].pnl == Decimal("10")
    assert result["BTCUSDT"].value == Decimal("0.005")


def test_pairs_come_out_in_alphabetical_order_and_no_trades_yield_no_pairs() -> None:
    assert by_pair([]) == ()
    result = by_pair([_trade("SOLUSDT", "1"), _trade("ETHUSDT", "1"), _trade("BTCUSDT", "1")])
    assert [p.pair for p in result] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


# ---------------------------------------------------------------------------
# Wins (design.md, unit 12f addendum, section G; spec: performance-reporting
# "A Pair's Win Rate Counts Closed Operations With A PnL Above Zero"; tasks.md
# 12f.9.1). A win is a closed operation whose PnL is above zero; a PnL of
# exactly zero is not a win and still counts in the total.
# ---------------------------------------------------------------------------


def test_a_win_is_a_pnl_above_zero_and_the_rate_is_wins_over_trades() -> None:
    """SOLUSDT +4.10, +0.80, +2.00, 0 and -1.25: five operations, three wins,
    the zero and the loss are not."""
    result = by_pair(
        [
            _trade("SOLUSDT", "4.10"),
            _trade("SOLUSDT", "0.80"),
            _trade("SOLUSDT", "2.00"),
            _trade("SOLUSDT", "0"),
            _trade("SOLUSDT", "-1.25"),
        ]
    )

    assert len(result) == 1
    assert result[0].trade_count == 5
    assert result[0].win_count == 3
    assert result[0].win_rate == Decimal("0.6")


def test_199_wins_in_200_are_a_rate_below_one() -> None:
    """One loss among 200 must never read as a perfect record: 0.995, not 1.
    Nothing is rounded in the domain (the wire rounds)."""
    trades = [_trade("SOLUSDT", "1") for _ in range(199)] + [_trade("SOLUSDT", "-1")]

    result = by_pair(trades)

    assert result[0].trade_count == 200
    assert result[0].win_count == 199
    assert result[0].win_rate == Decimal("0.995")


def test_a_pair_with_no_win_has_a_zero_rate_and_a_pair_that_won_every_operation_has_a_rate_of_one() -> None:  # noqa: E501
    """The two ends: a pair that never won is 0 (never absent), a pair that
    won every operation is exactly 1."""
    result = {
        p.pair: p
        for p in by_pair(
            [
                _trade("BTCUSDT", "-3"),
                _trade("BTCUSDT", "-1"),
                _trade("ETHUSDT", "2"),
                _trade("ETHUSDT", "0.01"),
                _trade("ETHUSDT", "9"),
            ]
        )
    }

    assert result["BTCUSDT"].win_count == 0
    assert result["BTCUSDT"].win_rate == Decimal(0)
    assert result["ETHUSDT"].win_count == 3
    assert result["ETHUSDT"].win_rate == Decimal(1)


def test_a_pnl_of_exactly_zero_is_not_a_win_and_counts_in_the_total() -> None:
    """Two operations closed at exactly 0: two trades, no win, rate 0."""
    result = by_pair([_trade("SOLUSDT", "0"), _trade("SOLUSDT", "0.000")])

    assert result[0].trade_count == 2
    assert result[0].win_count == 0
    assert result[0].win_rate == Decimal(0)


def test_a_trade_with_incomplete_fees_and_a_trade_with_no_capital_at_open_are_counted() -> None:
    """Every closed trade of the pair counts, as it does in ``trade_count`` and
    ``pnl``: one whose fees are incomplete and one with no capital at open are
    each counted by the PnL they have."""
    incomplete_fees = replace(_trade("SOLUSDT", "2"), fees_complete=False)
    no_capital = _trade("SOLUSDT", "3", capital=None)

    result = by_pair([incomplete_fees, no_capital, _trade("SOLUSDT", "-1")])

    assert result[0].trade_count == 3
    assert result[0].win_count == 2
    assert result[0].win_rate == Decimal(2) / Decimal(3)


def test_two_spellings_of_one_market_are_one_pair_with_its_wins() -> None:
    """Through the real derivation: allocation ``a`` opened ``SOLUSDT.P`` and
    closed ``SOLUSDT`` at +5; allocation ``b`` opened ``SOLUSDT_PERP`` and
    closed ``solusdt`` at -3. One pair, one win in two."""
    a, b = uuid4(), uuid4()
    derived = derive_trades(
        [
            _group(a, "BUY", "100", "SOLUSDT.P", at=OPENED),
            _group(a, "SELL", "105", "SOLUSDT", at=CLOSED),
            _group(b, "BUY", "100", "SOLUSDT_PERP", at=OPENED),
            _group(b, "SELL", "97", "solusdt", at=CLOSED),
        ]
    )

    result = by_pair(derived.closed)

    assert [(p.pair, p.trade_count, p.win_count, p.win_rate) for p in result] == [
        ("SOLUSDT", 2, 1, Decimal("0.5"))
    ]


def test_a_pair_removed_from_the_allowlist_keeps_its_wins() -> None:
    """Decision 15: the allowlist gates OPENS only. ``by_pair`` is given no
    allowlist, so SOLUSDT, removed after it traded, keeps its wins."""
    allowed_today = {"BTCUSDT"}
    trades = [_trade("SOLUSDT", "5"), _trade("SOLUSDT", "-2"), _trade("BTCUSDT", "10")]

    result = {p.pair: p for p in by_pair(trades)}

    assert "SOLUSDT" not in allowed_today
    assert result["SOLUSDT"].win_count == 1
    assert result["SOLUSDT"].win_rate == Decimal("0.5")
    assert result["BTCUSDT"].win_count == 1
    assert result["BTCUSDT"].win_rate == Decimal(1)

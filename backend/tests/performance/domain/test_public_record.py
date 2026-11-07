"""The public record: the author's real closed trades, added up as the panel adds its own
(tasks.md G.8, decisions 28, 31 and 34)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.curve import RangeName
from strategy_manager.performance.domain.public_record import (
    RecordPair,
    RecordRange,
    RecordReport,
    RecordTrade,
    build_public_record,
    build_record_report,
    closed_trades,
)

START = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
STRATEGY = uuid4()


def group(
    allocation: UUID,
    side: str,
    quantity: str,
    notional: str,
    *,
    at: datetime = START,
    fee: str = "0",
    symbol: str = "STXUSDT",
    settlement: str = "USDT",
    rehearsal: bool = False,
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation,
        strategy_id=STRATEGY,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency=settlement,
        symbol=symbol,
        side=side,
        fee_currency=settlement,
        quantity=Decimal(quantity),
        notional=Decimal(notional),
        fee=Decimal(fee),
        first_filled_at=at,
        last_filled_at=at,
        pool_total_at_open=None,
        rehearsal=rehearsal,
    )


def round_trip(
    opening: str,
    open_notional: str,
    close_notional: str,
    *,
    opened_at: datetime = START,
    closed_at: datetime | None = None,
    rehearsal: bool = False,
    fee: str = "0",
    symbol: str = "STXUSDT",
) -> list[FillGroup]:
    """One allocation of 2 base units, opened on ``opening``'s side and closed."""
    allocation = uuid4()
    closing = "SELL" if opening == "BUY" else "BUY"
    return [
        group(
            allocation,
            opening,
            "2",
            open_notional,
            at=opened_at,
            fee=fee,
            symbol=symbol,
            rehearsal=rehearsal,
        ),
        group(
            allocation,
            closing,
            "2",
            close_notional,
            at=closed_at or opened_at + timedelta(hours=1),
            fee=fee,
            symbol=symbol,
            rehearsal=rehearsal,
        ),
    ]


class TestATradesReturn:
    def test_a_long_returns_what_it_sold_over_what_it_bought_minus_one(self) -> None:
        closed_at = START + timedelta(hours=3)

        trades = closed_trades(round_trip("BUY", "200", "220", closed_at=closed_at))

        assert trades == (
            RecordTrade(opened_at=START, closed_at=closed_at, value=Decimal("0.1"), pair="STXUSDT"),
        )

    def test_a_short_returns_one_minus_what_it_bought_back_over_what_it_sold(self) -> None:
        trades = closed_trades(round_trip("SELL", "200", "220"))

        assert [trade.value for trade in trades] == [Decimal("-0.1")]

    def test_no_fee_reaches_the_return(self) -> None:
        trades = closed_trades(round_trip("BUY", "200", "220", fee="3"))

        assert [trade.value for trade in trades] == [Decimal("0.1")]

    def test_a_trade_closed_under_another_spelling_is_still_one_trade(self) -> None:
        allocation = uuid4()
        trades = closed_trades(
            [
                group(allocation, "BUY", "2", "200", symbol="STXUSDT.P"),
                group(allocation, "SELL", "2", "210", at=START + timedelta(hours=1)),
            ]
        )

        assert [trade.value for trade in trades] == [Decimal("0.05")]


class TestWhatCounts:
    def test_an_open_trade_counts_for_nothing(self) -> None:
        allocation = uuid4()
        record = build_public_record(
            [*round_trip("BUY", "200", "220"), group(allocation, "BUY", "2", "200")]
        )

        assert record.closed_trade_count == 1
        assert record.total_return == Decimal("0.1")

    def test_a_partly_closed_trade_counts_for_nothing(self) -> None:
        allocation = uuid4()
        record = build_public_record(
            [
                group(allocation, "BUY", "2", "200"),
                group(allocation, "SELL", "1", "150", at=START + timedelta(hours=1)),
            ]
        )

        assert record.closed_trade_count == 0

    def test_a_rehearsal_trade_never_counts_even_when_a_source_lets_it_through(self) -> None:
        record = build_public_record(
            [*round_trip("BUY", "200", "300", rehearsal=True), *round_trip("BUY", "200", "220")]
        )

        assert record.closed_trade_count == 1
        assert record.total_return == Decimal("0.1")

    def test_no_closed_trade_reads_zero_trades_and_zero_return(self) -> None:
        record = build_public_record([])

        assert record.closed_trade_count == 0
        assert record.total_return == Decimal(0)
        assert record.unresolved_allocation_ids == ()

    def test_an_allocation_that_cannot_be_split_is_reported_not_dropped(self) -> None:
        allocation = uuid4()
        record = build_public_record(
            [
                *round_trip("BUY", "200", "220"),
                group(allocation, "BUY", "2", "200", symbol="STXBTC", settlement="USDT"),
                group(allocation, "SELL", "2", "220", symbol="STXBTC", settlement="USDT"),
            ]
        )

        assert record.closed_trade_count == 1
        assert record.unresolved_allocation_ids == (allocation,)


class TestAddingUp:
    def test_trades_of_one_utc_day_are_summed_and_days_compounded(self) -> None:
        day = timedelta(days=1)
        record = build_public_record(
            [
                *round_trip("BUY", "200", "220", closed_at=START + timedelta(hours=1)),
                *round_trip("BUY", "200", "210", closed_at=START + timedelta(hours=2)),
                *round_trip("BUY", "200", "220", opened_at=START + day),
            ]
        )

        assert record.closed_trade_count == 3
        # (1 + 0.1 + 0.05) * (1 + 0.1) - 1
        assert record.total_return == Decimal("0.265")

    def test_a_trade_opened_after_another_closed_that_day_compounds_on_it(self) -> None:
        """Decision 40: the second opened an hour after the first closed."""
        record = build_public_record(
            [
                *round_trip("BUY", "200", "220", closed_at=START + timedelta(hours=1)),
                *round_trip(
                    "BUY",
                    "200",
                    "210",
                    opened_at=START + timedelta(hours=2),
                    closed_at=START + timedelta(hours=3),
                ),
            ]
        )

        assert record.total_return == Decimal("1.1") * Decimal("1.05") - 1

    def test_trades_are_listed_oldest_close_first(self) -> None:
        late = round_trip("BUY", "200", "220", closed_at=START + timedelta(hours=5))
        early = round_trip("BUY", "200", "180", closed_at=START + timedelta(hours=2))

        trades = closed_trades([*late, *early])

        assert [trade.value for trade in trades] == [Decimal("-0.1"), Decimal("0.1")]


NOW = START + timedelta(days=10)


def _small_record() -> list[FillGroup]:
    """Four closed trades. The first two overlap on 1 March (summed), the others fall
    on 2 and 5 March. The venue says ``STXUSDT`` and the alert said ``STXUSDT.P``."""
    day = timedelta(days=1)
    return [
        *round_trip("BUY", "200", "220", closed_at=START + timedelta(hours=1)),
        *round_trip(
            "BUY",
            "200",
            "210",
            symbol="STXUSDT.P",
            opened_at=START + timedelta(minutes=30),
            closed_at=START + timedelta(hours=2),
        ),
        *round_trip("SELL", "200", "220", symbol="BTCUSDT", opened_at=START + day),
        *round_trip("BUY", "200", "220", symbol="BTCUSDT", opened_at=START + 4 * day),
    ]


class TestTheReport:
    def test_the_curve_adds_overlapping_trades_and_compounds_days(self) -> None:
        report = build_record_report(_small_record(), NOW)

        assert [
            (point.day, point.daily_return, point.index, point.drawdown) for point in report.curve
        ] == [
            (date(2026, 3, 1), Decimal("0.15"), Decimal("1.15"), Decimal(0)),
            (date(2026, 3, 2), Decimal("-0.1"), Decimal("1.035"), Decimal("-0.1")),
            (date(2026, 3, 5), Decimal("0.1"), Decimal("1.1385"), Decimal("-0.01")),
        ]
        assert report.max_drawdown == Decimal("-0.1")
        assert report.closed_trade_count == 4

    def test_a_trade_opened_after_another_closed_that_day_compounds_on_it(self) -> None:
        report = build_record_report(
            [
                *round_trip("BUY", "200", "220", closed_at=START + timedelta(hours=1)),
                *round_trip(
                    "BUY",
                    "200",
                    "210",
                    opened_at=START + timedelta(hours=2),
                    closed_at=START + timedelta(hours=3),
                ),
            ],
            NOW,
        )

        [point] = report.curve
        assert point.index == Decimal("1.155")

    def test_the_origin_is_the_utc_day_of_the_earliest_opening(self) -> None:
        late_evening = datetime(2026, 3, 1, 23, 30, tzinfo=UTC)
        report = build_record_report(
            [
                *round_trip("BUY", "200", "220", opened_at=START + timedelta(days=3)),
                *round_trip("BUY", "200", "220", opened_at=late_evening),
            ],
            NOW,
        )

        assert report.origin == date(2026, 3, 1)
        assert report.curve[0].day == date(2026, 3, 2)

    def test_the_month_is_the_end_index_over_the_previous_month(self) -> None:
        april = round_trip("BUY", "200", "240", opened_at=datetime(2026, 4, 2, tzinfo=UTC))

        report = build_record_report([*_small_record(), *april], NOW + timedelta(days=60))

        assert [(m.year, m.month, m.value) for m in report.monthly] == [
            (2026, 3, Decimal("0.1385")),
            (2026, 4, Decimal("1.1385") * Decimal("1.2") / Decimal("1.1385") - 1),
        ]

    def test_a_range_is_the_record_of_the_trades_closed_in_its_window(self) -> None:
        report = build_record_report(_small_record(), NOW)

        assert [(r.range, r.value, r.trade_count) for r in report.ranges] == [
            (RangeName.D7, Decimal("0.1"), 1),
            (RangeName.D30, Decimal("0.1385"), 4),
            (RangeName.D90, Decimal("0.1385"), 4),
            (RangeName.Y1, Decimal("0.1385"), 4),
            (RangeName.ALL, Decimal("0.1385"), 4),
        ]

    def test_a_window_includes_its_start_instant(self) -> None:
        closed = START + timedelta(hours=1)
        report = build_record_report(
            round_trip("BUY", "200", "220", closed_at=closed), closed + timedelta(days=7)
        )

        assert report.ranges[0].trade_count == 1

    def test_a_pair_is_its_trades_compounded_and_its_wins_are_returns_above_zero(self) -> None:
        report = build_record_report(_small_record(), NOW)

        assert [
            (p.pair, p.trade_count, p.win_count, p.win_rate, p.value) for p in report.by_pair
        ] == [
            ("BTCUSDT", 2, 1, Decimal("0.5"), Decimal("0.9") * Decimal("1.1") - 1),
            ("STXUSDT", 2, 2, Decimal(1), Decimal("0.15")),
        ]

    def test_a_return_of_exactly_zero_is_not_a_win(self) -> None:
        report = build_record_report(round_trip("BUY", "200", "200"), NOW)

        [pair] = report.by_pair
        assert (pair.trade_count, pair.win_count, pair.win_rate) == (1, 0, Decimal(0))

    def test_no_closed_trade_reads_an_empty_report(self) -> None:
        report = build_record_report([], NOW)

        assert report.origin is None
        assert report.curve == ()
        assert report.monthly == ()
        assert report.by_pair == ()
        assert report.closed_trade_count == 0
        assert report.max_drawdown == Decimal(0)
        assert [(r.value, r.trade_count) for r in report.ranges] == [(Decimal(0), 0)] * 5

    def test_a_rehearsal_trade_never_reaches_the_report(self) -> None:
        report = build_record_report(
            [*round_trip("BUY", "200", "300", rehearsal=True), *round_trip("BUY", "200", "220")],
            NOW,
        )

        assert report.closed_trade_count == 1
        assert report.curve[0].index == Decimal("1.1")
        assert report.by_pair[0].trade_count == 1

    def test_an_unresolved_allocation_is_reported(self) -> None:
        allocation = uuid4()
        report = build_record_report(
            [
                group(allocation, "BUY", "2", "200", symbol="STXBTC"),
                group(allocation, "SELL", "2", "220", symbol="STXBTC"),
            ],
            NOW,
        )

        assert report.unresolved_allocation_ids == (allocation,)

    def test_it_agrees_with_the_total_of_build_public_record(self) -> None:
        groups = _small_record()

        assert build_record_report(groups, NOW).curve[-1].index - 1 == (
            build_public_record(groups).total_return
        )

    def test_it_carries_no_amount(self) -> None:
        fields = {name for cls in (RecordRange, RecordPair, RecordReport) for name in cls.__slots__}
        assert not {name for name in fields if "pnl" in name or "amount" in name or "money" in name}

"""The public record: the author's real closed trades, added up as the panel adds its own
(tasks.md G.8, decisions 28, 31 and 34)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.public_record import (
    RecordTrade,
    build_public_record,
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
) -> list[FillGroup]:
    """One allocation of 2 base units, opened on ``opening``'s side and closed."""
    allocation = uuid4()
    closing = "SELL" if opening == "BUY" else "BUY"
    return [
        group(allocation, opening, "2", open_notional, at=opened_at, fee=fee, rehearsal=rehearsal),
        group(
            allocation,
            closing,
            "2",
            close_notional,
            at=closed_at or opened_at + timedelta(hours=1),
            fee=fee,
            rehearsal=rehearsal,
        ),
    ]


class TestATradesReturn:
    def test_a_long_returns_what_it_sold_over_what_it_bought_minus_one(self) -> None:
        closed_at = START + timedelta(hours=3)

        trades = closed_trades(round_trip("BUY", "200", "220", closed_at=closed_at))

        assert trades == (RecordTrade(opened_at=START, closed_at=closed_at, value=Decimal("0.1")),)

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

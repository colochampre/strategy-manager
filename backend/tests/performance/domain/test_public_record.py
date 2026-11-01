"""The public record: closed trades from a strategy's signals, added up as the panel adds its own
(tasks.md F.3, decisions 15 and 28)."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from strategy_manager.performance.domain.public_record import (
    RecordSignal,
    RecordTrade,
    build_public_record,
    closed_trades,
)
from strategy_manager.shared.domain.errors import InvariantViolation

SYMBOL = "STXUSDT.P"
START = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def signal(size: str, price: str, minute: int = 0, symbol: str = SYMBOL) -> RecordSignal:
    return RecordSignal(
        symbol=symbol,
        received_at=START + timedelta(minutes=minute),
        position_size=Decimal(size),
        price=Decimal(price),
    )


def chain(
    *steps: tuple[str, str], symbol: str = SYMBOL, first_minute: int = 0
) -> list[RecordSignal]:
    """One signal per (position_size, price), a minute apart."""
    return [
        signal(size, price, first_minute + minute, symbol)
        for minute, (size, price) in enumerate(steps)
    ]


def values(signals: list[RecordSignal]) -> list[Decimal]:
    return [trade.value for trade in closed_trades(signals)]


def trade_closing_at(moment: datetime, gain: str, symbol: str = SYMBOL) -> list[RecordSignal]:
    """A long from 100 that returns ``gain`` and closes at ``moment``."""
    exit_price = Decimal(100) * (Decimal(1) + Decimal(gain))
    return [
        RecordSignal(symbol, moment - timedelta(minutes=1), Decimal(1), Decimal(100)),
        RecordSignal(symbol, moment, Decimal(0), exit_price),
    ]


class TestAClosedTrade:
    def test_a_long_returns_exit_over_entry_minus_one(self) -> None:
        trades = closed_trades(chain(("1", "100"), ("0", "110")))

        closed_at = START + timedelta(minutes=1)
        assert trades == (RecordTrade(symbol=SYMBOL, closed_at=closed_at, value=Decimal("0.1")),)

    def test_a_losing_long_returns_a_negative_value(self) -> None:
        assert values(chain(("1", "100"), ("0", "90"))) == [Decimal("-0.1")]

    def test_a_short_returns_one_minus_exit_over_entry(self) -> None:
        assert values(chain(("-1", "100"), ("0", "90"))) == [Decimal("0.1")]

    def test_a_losing_short_returns_a_negative_value(self) -> None:
        assert values(chain(("-1", "100"), ("0", "110"))) == [Decimal("-0.1")]

    def test_the_side_is_the_sign_whatever_the_size(self) -> None:
        assert values(chain(("-0.25", "100"), ("0", "90"))) == [Decimal("0.1")]
        assert values(chain(("40", "100"), ("0", "90"))) == [Decimal("-0.1")]


class TestReverse:
    def test_a_long_flipped_to_a_short_closes_and_opens_at_the_same_price(self) -> None:
        trades = closed_trades(chain(("1", "100"), ("-1", "110"), ("0", "99")))

        assert [trade.value for trade in trades] == [Decimal("0.1"), Decimal("0.1")]
        assert [trade.closed_at for trade in trades] == [
            START + timedelta(minutes=1),
            START + timedelta(minutes=2),
        ]

    def test_a_short_flipped_to_a_long_closes_and_opens_at_the_same_price(self) -> None:
        assert values(chain(("-1", "100"), ("1", "90"), ("0", "99"))) == [
            Decimal("0.1"),
            Decimal("0.1"),
        ]

    def test_a_flip_leaves_the_new_side_open_and_it_counts_for_nothing_yet(self) -> None:
        assert values(chain(("1", "100"), ("-1", "110"))) == [Decimal("0.1")]


class TestWhatIsSkipped:
    def test_a_larger_size_on_the_same_side_leaves_the_entry_as_it_is(self) -> None:
        assert values(chain(("1", "100"), ("2", "150"), ("0", "110"))) == [Decimal("0.1")]

    def test_a_smaller_size_on_the_same_side_leaves_the_entry_as_it_is(self) -> None:
        assert values(chain(("-2", "100"), ("-1", "50"), ("0", "90"))) == [Decimal("0.1")]

    def test_zero_to_zero_before_anything_opened_is_skipped(self) -> None:
        assert values(chain(("0", "50"), ("1", "100"), ("0", "110"))) == [Decimal("0.1")]

    def test_zero_to_zero_after_a_close_is_skipped(self) -> None:
        assert values(chain(("1", "100"), ("0", "110"), ("0", "500"))) == [Decimal("0.1")]

    def test_a_trade_that_never_closed_counts_for_nothing(self) -> None:
        assert values(chain(("1", "100"), ("2", "110"))) == []


class TestTheChain:
    def test_signals_are_read_in_the_order_they_were_received(self) -> None:
        opened, closed = chain(("1", "100"), ("0", "110"))

        assert values([closed, opened]) == [Decimal("0.1")]

    def test_a_chain_can_open_again_after_it_closed(self) -> None:
        assert values(chain(("1", "100"), ("0", "110"), ("-1", "200"), ("0", "180"))) == [
            Decimal("0.1"),
            Decimal("0.1"),
        ]

    def test_two_symbols_keep_their_own_chains(self) -> None:
        stx = chain(("1", "100"), ("0", "110"), symbol="STXUSDT.P")
        btc = chain(("-1", "1000"), ("0", "800"), symbol="BTCUSDT.P")

        interleaved = [btc[0], stx[0], stx[1], btc[1]]

        assert sorted(values(interleaved)) == [Decimal("0.1"), Decimal("0.2")]

    @pytest.mark.parametrize("other", ["STXUSDT", "STXUSDT_PERP"])
    def test_a_symbol_in_another_spelling_keeps_its_own_chain(self, other: str) -> None:
        opened = signal("1", "100", 0, symbol="STXUSDT.P")
        elsewhere = signal("0", "110", 1, symbol=other)

        assert values([opened, elsewhere]) == []

    def test_a_chain_in_each_spelling_closes_on_its_own(self) -> None:
        tradingview = chain(("1", "100"), ("0", "110"), symbol="STXUSDT.P")
        bare = chain(("1", "200"), ("0", "220"), symbol="STXUSDT", first_minute=10)

        record = build_public_record([*tradingview, *bare])

        assert record.closed_trade_count == 2


class TestTheOrderOfTheTrades:
    def test_trades_come_oldest_close_first_whichever_chain_came_first(self) -> None:
        later = chain(("1", "100"), ("0", "110"), symbol="STXUSDT.P", first_minute=10)
        earlier = chain(("1", "100"), ("0", "110"), symbol="BTCUSDT.P")

        trades = closed_trades([*later, *earlier])

        assert [trade.symbol for trade in trades] == ["BTCUSDT.P", "STXUSDT.P"]


class TestTheRecord:
    def test_a_strategy_with_no_closed_trade_has_a_record_of_nothing(self) -> None:
        record = build_public_record(chain(("1", "100")))

        assert record.closed_trade_count == 0
        assert record.total_return == Decimal(0)

    def test_no_signals_at_all_is_a_record_of_nothing(self) -> None:
        record = build_public_record([])

        assert record.closed_trade_count == 0
        assert record.total_return == Decimal(0)

    def test_it_counts_each_side_of_a_flip_only_once_it_closed(self) -> None:
        record = build_public_record(chain(("1", "100"), ("-1", "110"), ("0", "99"), ("1", "50")))

        assert record.closed_trade_count == 2

    def test_trades_of_one_utc_day_are_summed_not_compounded(self) -> None:
        signals = [
            *trade_closing_at(START, "0.02", symbol="AAAUSDT.P"),
            *trade_closing_at(START + timedelta(hours=1), "0.01", symbol="BBBUSDT.P"),
        ]

        assert build_public_record(signals).total_return == Decimal("0.03")

    def test_days_are_compounded(self) -> None:
        signals = [
            *trade_closing_at(START, "0.1"),
            *trade_closing_at(START + timedelta(days=1), "0.1"),
        ]

        assert build_public_record(signals).total_return == Decimal("0.21")

    def test_a_loss_compounds_with_the_gain_after_it(self) -> None:
        signals = [
            *trade_closing_at(START, "-0.5"),
            *trade_closing_at(START + timedelta(days=1), "1"),
        ]

        assert build_public_record(signals).total_return == Decimal(0)

    def test_two_percent_on_five_pairs_in_one_day_shows_ten_percent(self) -> None:
        signals = [
            step
            for pair in ("AAA", "BBB", "CCC", "DDD", "EEE")
            for step in trade_closing_at(START, "0.02", symbol=f"{pair}USDT.P")
        ]

        record = build_public_record(signals)

        assert record.closed_trade_count == 5
        assert record.total_return == Decimal("0.10")

    def test_the_day_is_the_utc_day_of_the_close_not_the_day_of_its_offset(self) -> None:
        buenos_aires = timezone(timedelta(hours=-3))
        evening_there = datetime(2026, 3, 1, 22, 0, tzinfo=buenos_aires)
        signals = [
            *trade_closing_at(evening_there, "0.02", symbol="AAAUSDT.P"),
            *trade_closing_at(datetime(2026, 3, 2, 3, 0, tzinfo=UTC), "0.01", symbol="BBBUSDT.P"),
        ]

        assert build_public_record(signals).total_return == Decimal("0.03")

    def test_a_close_with_no_zone_is_refused_rather_than_guessed(self) -> None:
        naive = RecordSignal(SYMBOL, datetime(2026, 3, 1, 13, 0), Decimal(0), Decimal(110))
        opened = RecordSignal(SYMBOL, datetime(2026, 3, 1, 12, 0), Decimal(1), Decimal(100))

        with pytest.raises(InvariantViolation, match="naive datetime"):
            build_public_record([opened, naive])

"""The unrealized PnL of an open position (RD.3b): what the open size would make
at the venue's mark, in the settlement currency, before fees."""

from decimal import Decimal

from strategy_manager.performance.domain.closed_trade import Direction
from strategy_manager.performance.domain.open_position import (
    OpenPositionFigures,
    unrealized_pnl,
)


def _figures(side: Direction, *, size: str = "100", entry: str = "0.45") -> OpenPositionFigures:
    return OpenPositionFigures(
        side=side,
        base_currency="STX",
        size=Decimal(size),
        opened_size=Decimal(size),
        entry_price=Decimal(entry),
    )


def test_a_long_gains_when_the_mark_is_above_its_entry() -> None:
    assert unrealized_pnl(_figures(Direction.LONG), Decimal("0.47")) == Decimal("2.00")


def test_a_long_loses_when_the_mark_is_below_its_entry() -> None:
    assert unrealized_pnl(_figures(Direction.LONG), Decimal("0.44")) == Decimal("-1.00")


def test_a_short_gains_when_the_mark_is_below_its_entry() -> None:
    assert unrealized_pnl(_figures(Direction.SHORT), Decimal("0.44")) == Decimal("1.00")


def test_a_short_loses_when_the_mark_is_above_its_entry() -> None:
    assert unrealized_pnl(_figures(Direction.SHORT), Decimal("0.47")) == Decimal("-2.00")


def test_it_uses_the_open_size_not_the_size_the_position_opened_with() -> None:
    figures = OpenPositionFigures(
        side=Direction.LONG,
        base_currency="STX",
        size=Decimal("40"),
        opened_size=Decimal("100"),
        entry_price=Decimal("0.45"),
    )

    assert unrealized_pnl(figures, Decimal("0.50")) == Decimal("2.00")


def test_a_mark_equal_to_the_entry_is_zero() -> None:
    assert unrealized_pnl(_figures(Direction.LONG), Decimal("0.45")) == Decimal("0")

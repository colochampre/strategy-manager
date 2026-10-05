"""Unit tests: ``operation_figures`` -- the entry price, exit price, size and
base currency of one operation, derived from the aggregates of one allocation
(design.md, addendum "a strategy's operations", section B).

Pure ``Decimal`` domain, no I/O. Every expected figure is an exact ``Decimal``.

**Binding testing lesson**: a symbol has three spellings (TradingView
``STXUSDT.P``, venue bare ``STXUSDT``, Pionex ``STXUSDT_PERP``). The two sides
of one operation below are written under DIFFERENT spellings on purpose.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.performance.domain.closed_trade import Direction, FillGroup
from strategy_manager.performance.domain.derive_trade import derive_trade
from strategy_manager.performance.domain.operation import (
    OperationFigures,
    operation_fees,
    operation_figures,
)

OPENED = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
CLOSED = datetime(2026, 9, 2, 11, 30, tzinfo=UTC)
STRATEGY = uuid4()


def _group(
    allocation_id: UUID,
    *,
    side: str,
    quantity: str,
    notional: str,
    symbol: str,
    fee: str = "0",
    fee_currency: str = "USDT",
    at: datetime = OPENED,
) -> FillGroup:
    return FillGroup(
        allocation_id=allocation_id,
        strategy_id=STRATEGY,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        side=side,
        fee_currency=fee_currency,
        quantity=Decimal(quantity),
        notional=Decimal(notional),
        fee=Decimal(fee),
        first_filled_at=at,
        last_filled_at=at,
        pool_total_at_open=Decimal("1000"),
        rehearsal=False,
    )


def test_one_fill_per_side_gives_that_fills_prices_and_the_base_currency() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", quantity="1250", notional="564.0", symbol="STXUSDT.P", at=OPENED),
        _group(a, side="SELL", quantity="1250", notional="578.875", symbol="STXUSDT", at=CLOSED),
    ]

    figures = operation_figures(groups, Direction.LONG)

    assert figures == OperationFigures(
        base_currency="STX",
        entry_price=Decimal("0.4512"),
        exit_price=Decimal("0.4631"),
        size=Decimal("1250"),
    )


def test_the_entry_price_is_weighted_by_quantity_not_a_mean_of_group_averages() -> None:
    """100 at 0.40, 300 at 0.44 and 600 at 0.46 enter at (40 + 132 + 276) / 1000
    = 0.448; a mean of the three averages would say 0.4333..."""
    a = uuid4()
    groups = [
        _group(a, side="BUY", quantity="100", notional="40", symbol="STXUSDT.P", at=OPENED),
        _group(a, side="BUY", quantity="300", notional="132", symbol="STXUSDT", at=OPENED),
        _group(a, side="BUY", quantity="600", notional="276", symbol="STXUSDT_PERP", at=OPENED),
        _group(a, side="SELL", quantity="1000", notional="500", symbol="STXUSDT", at=CLOSED),
    ]

    figures = operation_figures(groups, Direction.LONG)

    assert figures is not None
    assert figures.entry_price == Decimal("0.448")
    assert figures.size == Decimal("1000")
    assert figures.exit_price == Decimal("0.5")


def test_a_short_enters_on_its_sell_side() -> None:
    a = uuid4()
    groups = [
        _group(a, side="SELL", quantity="2", notional="300", symbol="SOLUSDT.P", at=OPENED),
        _group(a, side="BUY", quantity="2", notional="280", symbol="SOLUSDT", at=CLOSED),
    ]

    figures = operation_figures(groups, Direction.SHORT)

    assert figures == OperationFigures(
        base_currency="SOL",
        entry_price=Decimal("150"),
        exit_price=Decimal("140"),
        size=Decimal("2"),
    )


def test_size_is_the_opening_quantity_when_a_base_currency_fee_makes_the_sides_differ() -> None:
    """Pionex spot takes a BUY's fee in the base coin: 1000 bought, 999 sold."""
    a = uuid4()
    groups = [
        _group(
            a,
            side="BUY",
            quantity="1000",
            notional="500",
            symbol="STXUSDT",
            fee="1",
            fee_currency="STX",
            at=OPENED,
        ),
        _group(a, side="SELL", quantity="999", notional="499.5", symbol="STXUSDT", at=CLOSED),
    ]

    figures = operation_figures(groups, Direction.LONG)

    assert figures is not None
    assert figures.size == Decimal("1000")
    assert figures.entry_price == Decimal("0.5")
    assert figures.exit_price == Decimal("0.5")


@pytest.mark.parametrize(
    ("open_side", "close_side", "open_notional", "close_notional", "direction"),
    [
        ("BUY", "SELL", "1000", "1030", Direction.LONG),
        ("SELL", "BUY", "1000", "970", Direction.SHORT),
    ],
)
def test_pnl_equals_exit_minus_entry_times_size_times_sign_minus_fees(
    open_side: str,
    close_side: str,
    open_notional: str,
    close_notional: str,
    direction: Direction,
) -> None:
    a = uuid4()
    groups = [
        _group(
            a,
            side=open_side,
            quantity="10",
            notional=open_notional,
            symbol="SOLUSDT.P",
            fee="0.5",
            at=OPENED,
        ),
        _group(
            a,
            side=close_side,
            quantity="10",
            notional=close_notional,
            symbol="SOLUSDT",
            fee="0.6",
            at=CLOSED,
        ),
    ]
    trade = derive_trade(groups)
    assert trade is not None
    assert trade.direction is direction

    figures = operation_figures(groups, trade.direction)
    fees = operation_fees(groups)

    assert figures is not None
    sign = Decimal(1) if direction is Direction.LONG else Decimal(-1)
    assert (figures.exit_price - figures.entry_price) * figures.size * sign - fees.fees == trade.pnl


def test_a_quotient_is_computed_in_a_sixty_digit_context() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", quantity="3", notional="1", symbol="STXUSDT.P", at=OPENED),
        _group(a, side="SELL", quantity="3", notional="2", symbol="STXUSDT", at=CLOSED),
    ]

    figures = operation_figures(groups, Direction.LONG)

    assert figures is not None
    assert figures.entry_price == Decimal("0." + "3" * 60)
    assert figures.exit_price == Decimal("0." + "6" * 59 + "7")


@pytest.mark.parametrize(
    ("closing_quantity", "closing_notional", "opening_quantity", "opening_notional"),
    [
        ("0", "10", "1", "10"),
        ("1", "0", "1", "10"),
        ("1", "10", "0", "10"),
        ("1", "10", "1", "0"),
    ],
)
def test_a_side_whose_quantity_or_notional_is_not_above_zero_gives_none_and_never_divides(
    closing_quantity: str,
    closing_notional: str,
    opening_quantity: str,
    opening_notional: str,
) -> None:
    a = uuid4()
    groups = [
        _group(
            a,
            side="BUY",
            quantity=opening_quantity,
            notional=opening_notional,
            symbol="STXUSDT.P",
            at=OPENED,
        ),
        _group(
            a,
            side="SELL",
            quantity=closing_quantity,
            notional=closing_notional,
            symbol="STXUSDT",
            at=CLOSED,
        ),
    ]

    assert operation_figures(groups, Direction.LONG) is None


def test_fills_naming_two_markets_give_none() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", quantity="1", notional="10", symbol="STXUSDT", at=OPENED),
        _group(a, side="SELL", quantity="1", notional="11", symbol="SOLUSDT", at=CLOSED),
    ]

    assert operation_figures(groups, Direction.LONG) is None


def test_two_spellings_of_one_market_are_not_a_disagreement() -> None:
    a = uuid4()
    groups = [
        _group(a, side="BUY", quantity="1", notional="10", symbol="STXUSDT.P", at=OPENED),
        _group(a, side="BUY", quantity="1", notional="12", symbol="STXUSDT_PERP", at=OPENED),
        _group(a, side="SELL", quantity="2", notional="25", symbol="stxusdt", at=CLOSED),
    ]

    figures = operation_figures(groups, Direction.LONG)

    assert figures == OperationFigures(
        base_currency="STX",
        entry_price=Decimal("11"),
        exit_price=Decimal("12.5"),
        size=Decimal("2"),
    )

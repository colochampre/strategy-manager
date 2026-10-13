"""T8, the domain tables of an open position (design addendum "open positions",
sections D and E; CLAUDE.md rule 7).

Pure ``Decimal`` over the fill aggregates of ONE allocation: nothing is
converted, nothing sums two pools, and nothing raises for a row. Prices are
quotients taken in a 60-digit context and rounded to 18 places only at the wire.

A symbol is spelled differently on each side of a boundary (rule R7): the
ledger's fills as ``STXUSDT.P``, a booked fill as ``STXUSDT``.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from strategy_manager.performance.domain.closed_trade import Direction
from strategy_manager.performance.domain.open_position import (
    FiguresMissing,
    FillAggregate,
    OpenPositionFigures,
    open_position_figures,
)
from strategy_manager.shared.infrastructure.wire import price as wire_price

OPENED = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
ALLOCATION = uuid4()
STRATEGY = uuid4()


def _fill(
    side: str,
    quantity: str,
    price: str | None = "100",
    *,
    notional: str | None = None,
    symbol: str = "SOLUSDT.P",
    fee: str = "0",
    fee_currency: str = "USDT",
    minutes: int = 0,
    settlement: str = "USDT",
    allocation_id: UUID = ALLOCATION,
) -> FillAggregate:
    qty = Decimal(quantity)
    value = Decimal(notional) if notional is not None else qty * Decimal(price or "0")
    return FillAggregate(
        allocation_id=allocation_id,
        strategy_id=STRATEGY,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency=settlement,
        symbol=symbol,
        side=side,
        fee_currency=fee_currency,
        quantity=qty,
        notional=value,
        fee=Decimal(fee),
        first_filled_at=OPENED + timedelta(minutes=minutes),
        fill_count=1,
    )


def _figures(groups: Sequence[FillAggregate]) -> OpenPositionFigures:
    result = open_position_figures(groups)
    assert isinstance(result, OpenPositionFigures), f"expected the five figures, got {result!r}"
    return result


def _missing(groups: Sequence[FillAggregate]) -> FiguresMissing:
    result = open_position_figures(groups)
    assert isinstance(result, FiguresMissing), f"expected a reason, got figures {result!r}"
    return result


# --- the figures ---------------------------------------------------------------


def test_one_fill_is_a_long_with_its_own_size_and_price() -> None:
    figures = _figures([_fill("BUY", "0.5", "100", fee="0.02")])

    assert figures == OpenPositionFigures(
        side=Direction.LONG,
        base_currency="SOL",
        size=Decimal("0.5"),
        opened_size=Decimal("0.5"),
        entry_price=Decimal("100"),
    )


def test_several_fills_average_by_quantity() -> None:
    figures = _figures(
        [
            _fill("BUY", "0.1", "100", minutes=0),
            _fill("BUY", "0.1", "110", minutes=1),
            _fill("BUY", "0.3", "120", minutes=2),
        ]
    )

    assert (figures.opened_size, figures.size, figures.entry_price) == (
        Decimal("0.5"),
        Decimal("0.5"),
        Decimal("114"),
    )


def test_a_position_closed_in_part_keeps_what_it_was_opened_at() -> None:
    figures = _figures(
        [
            _fill("BUY", "0.5", "100", symbol="AAVEUSDT.P"),
            _fill("SELL", "0.2", "120", symbol="AAVEUSDT", minutes=5, fee="0.01"),
        ]
    )

    assert figures.side is Direction.LONG
    assert figures.base_currency == "AAVE"
    assert (figures.size, figures.opened_size, figures.entry_price) == (
        Decimal("0.3"),
        Decimal("0.5"),
        Decimal("100"),
    )


def test_a_fee_in_the_base_currency_shrinks_the_size_and_not_the_opened_size() -> None:
    figures = _figures([_fill("BUY", "1", "100", fee="0.001", fee_currency="SOL")])

    assert (figures.size, figures.opened_size) == (Decimal("0.999"), Decimal("1"))
    assert figures.entry_price == Decimal("100")


def test_the_fee_currency_is_compared_upper_cased() -> None:
    figures = _figures([_fill("BUY", "1", "100", fee="0.001", fee_currency="sol")])

    assert figures.size == Decimal("0.999")


def test_a_fee_in_a_third_currency_does_not_touch_the_size() -> None:
    figures = _figures([_fill("BUY", "1", "100", fee="0.3", fee_currency="BNB")])

    assert figures.size == Decimal("1")


def test_a_short_is_the_held_side_sell() -> None:
    figures = _figures([_fill("SELL", "0.3", "200", symbol="AAVEUSDT.P")])

    assert figures == OpenPositionFigures(
        side=Direction.SHORT,
        base_currency="AAVE",
        size=Decimal("0.3"),
        opened_size=Decimal("0.3"),
        entry_price=Decimal("200"),
    )


def test_a_short_closed_in_part_averages_its_sells_only() -> None:
    figures = _figures(
        [
            _fill("SELL", "1", "50", symbol="STXUSDT.P"),
            _fill("BUY", "0.4", "40", symbol="STXUSDT", minutes=3),
        ]
    )

    assert figures.side is Direction.SHORT
    assert (figures.size, figures.opened_size, figures.entry_price) == (
        Decimal("0.6"),
        Decimal("1"),
        Decimal("50"),
    )


def test_two_spellings_of_one_market_are_one_market() -> None:
    figures = _figures(
        [
            _fill("BUY", "2", "10", symbol="STXUSDT.P"),
            _fill("BUY", "2", "20", symbol="STXUSDT", minutes=1),
            _fill("SELL", "1", "30", symbol="stxusdt_perp", minutes=2),
        ]
    )

    assert figures.base_currency == "STX"
    assert (figures.size, figures.opened_size, figures.entry_price) == (
        Decimal("3"),
        Decimal("4"),
        Decimal("15"),
    )


def test_a_quotient_is_taken_in_a_wide_context_and_rounded_only_at_the_wire() -> None:
    figures = _figures([_fill("BUY", "3", notional="100")])

    with localcontext() as context:
        context.prec = 60
        exact = Decimal(100) / Decimal(3)
    assert figures.entry_price == exact
    assert wire_price(figures.entry_price) == "33.333333333333333333"


def test_the_fills_order_does_not_change_the_figures() -> None:
    fills = [
        _fill("BUY", "0.5", "100", minutes=0),
        _fill("SELL", "0.2", "120", minutes=5),
        _fill("BUY", "0.1", "90", minutes=9),
    ]

    assert _figures(fills) == _figures(list(reversed(fills)))


# --- the reasons ---------------------------------------------------------------


def test_a_net_that_flipped_has_no_figures() -> None:
    reason = _missing([_fill("BUY", "0.5", "100"), _fill("SELL", "0.8", "100", minutes=4)])

    assert reason is FiguresMissing.FLIPPED


def test_a_short_that_flipped_to_long_has_no_figures() -> None:
    reason = _missing([_fill("SELL", "0.5", "100"), _fill("BUY", "0.8", "100", minutes=4)])

    assert reason is FiguresMissing.FLIPPED


def test_fills_that_name_two_markets_have_no_figures() -> None:
    reason = _missing(
        [
            _fill("BUY", "0.5", "100", symbol="SOLUSDT.P"),
            _fill("BUY", "0.5", "100", symbol="AAVEUSDT", minutes=1),
        ]
    )

    assert reason is FiguresMissing.SEVERAL_MARKETS


def test_a_symbol_that_cannot_be_split_has_no_figures() -> None:
    reason = _missing([_fill("BUY", "0.5", "100", symbol="XYZBTC")])

    assert reason is FiguresMissing.UNRESOLVED_SYMBOL


def test_an_unresolved_symbol_is_the_reason_even_when_there_are_two_markets() -> None:
    reason = _missing(
        [
            _fill("BUY", "0.5", "100", symbol="SOLUSDT.P"),
            _fill("BUY", "0.5", "100", symbol="XYZBTC", minutes=1),
        ]
    )

    assert reason is FiguresMissing.UNRESOLVED_SYMBOL


def test_a_net_of_exactly_zero_is_inconsistent_never_a_size_of_zero() -> None:
    reason = _missing([_fill("BUY", "1", "100"), _fill("SELL", "1", "110", minutes=2)])

    assert reason is FiguresMissing.INCONSISTENT


def test_a_purchase_shrunk_to_nothing_by_its_base_fee_is_inconsistent() -> None:
    reason = _missing([_fill("BUY", "1", "100", fee="1", fee_currency="SOL")])

    assert reason is FiguresMissing.INCONSISTENT


def test_a_held_side_with_no_notional_is_inconsistent() -> None:
    reason = _missing([_fill("BUY", "0.5", notional="0")])

    assert reason is FiguresMissing.INCONSISTENT


def test_a_held_side_with_no_quantity_is_inconsistent_and_does_not_divide() -> None:
    # A SELL of nothing whose fee was charged in the base currency: the net is
    # below zero and the earliest fill is a SELL, so the held side is the SELL
    # side, whose quantity is zero. The divisor is checked before the division.
    reason = _missing([_fill("SELL", "0", notional="0", fee="0.1", fee_currency="SOL")])

    assert reason is FiguresMissing.INCONSISTENT


def test_no_groups_at_all_is_inconsistent_and_does_not_raise() -> None:
    assert open_position_figures([]) is FiguresMissing.INCONSISTENT

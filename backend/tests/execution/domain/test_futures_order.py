"""The futures order and its sizing.

The arithmetic here is the single most dangerous line in the futures adapter:
getting the leverage factor wrong does not produce a slightly wrong order, it
produces one off by the whole leverage multiple.
"""

from decimal import Decimal

import pytest

from strategy_manager.execution.domain.futures_order import (
    FuturesMarketOrder,
    close_futures_order,
    futures_position_size,
    open_futures_order,
    protective_stop_price,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.domain.errors import InvariantViolation


def test_granted_is_margin_so_the_size_is_multiplied_by_leverage() -> None:
    """100 USDT of margin at 5x supports 500 USDT of notional. Reading the
    granted amount as notional instead would deploy 20 USDT of the 100 the
    allocation engine set aside."""
    size = futures_position_size(
        granted=Decimal("100"), leverage=Decimal("5"), price=Decimal("64000")
    )

    assert size * Decimal("64000") == Decimal("500")


def test_the_margin_consumed_returns_to_the_granted_amount() -> None:
    """The property that makes the reservation honest: notional divided by
    leverage is the margin, and it must come back to what was granted
    (CLAUDE.md rule 4).

    Not EXACTLY, and that is worth stating rather than hiding. ``granted *
    leverage / price`` is a real division, and ``Decimal`` carries 28
    significant digits, so a price that does not divide evenly leaves a
    residue far below the smallest tradable unit. The adapter then truncates
    the size DOWN to the symbol's base step, which moves the margin actually
    consumed further below the grant -- never above it. Under is dust; over
    would spend capital the allocation engine never granted.
    """
    granted, leverage, price = Decimal("250"), Decimal("20"), Decimal("3175.5")

    size = futures_position_size(granted=granted, leverage=leverage, price=price)
    round_tripped = (size * price) / leverage

    assert abs(round_tripped - granted) < Decimal("1e-24")


def test_leverage_multiplies_before_the_division() -> None:
    """Dividing first and multiplying after applies the leverage factor to an
    already-inexact quotient, and the error scales with the leverage."""
    granted, price = Decimal("100"), Decimal("3")

    assert futures_position_size(
        granted=granted, leverage=Decimal("7"), price=price
    ) == granted * Decimal("7") / price


def test_one_times_leverage_is_the_notional_case() -> None:
    size = futures_position_size(
        granted=Decimal("100"), leverage=Decimal("1"), price=Decimal("50")
    )

    assert size == Decimal("2")


@pytest.mark.parametrize(
    ("granted", "leverage", "price"),
    [
        (Decimal("0"), Decimal("5"), Decimal("100")),
        (Decimal("-1"), Decimal("5"), Decimal("100")),
        (Decimal("100"), Decimal("0"), Decimal("100")),
        (Decimal("100"), Decimal("-5"), Decimal("100")),
        (Decimal("100"), Decimal("5"), Decimal("0")),
        (Decimal("100"), Decimal("5"), Decimal("-100")),
    ],
)
def test_a_non_positive_input_is_refused_rather_than_sized(
    granted: Decimal, leverage: Decimal, price: Decimal
) -> None:
    """A zero leverage would divide the position to nothing and a negative one
    would invert its direction. Neither is a number to carry forward."""
    with pytest.raises(InvariantViolation):
        futures_position_size(granted=granted, leverage=leverage, price=price)


def test_an_opening_order_is_never_reduce_only() -> None:
    """An order built from granted capital is opening exposure by definition.
    ``reduce_only`` on it would have the venue refuse the whole trade."""
    order = open_futures_order(
        side=OrderSide.BUY,
        client_order_id="abc",
        symbol="BTC_USDT_PERP",
        granted=Decimal("100"),
        leverage=Decimal("5"),
        price=Decimal("64000"),
    )

    assert order.reduce_only is False
    assert order.leverage == Decimal("5")
    assert order.base_size == Decimal("100") * Decimal("5") / Decimal("64000")


def test_an_opening_order_sizes_a_sell_the_same_way_as_a_buy() -> None:
    """This is the whole reason futures needs its own type: MARKET_QTY is
    denominated in the base currency whichever way it goes, so a short opens
    with the same arithmetic a long does."""
    common = {
        "client_order_id": "abc",
        "symbol": "BTC_USDT_PERP",
        "granted": Decimal("100"),
        "leverage": Decimal("5"),
        "price": Decimal("64000"),
    }

    buy = open_futures_order(side=OrderSide.BUY, **common)  # type: ignore[arg-type]
    sell = open_futures_order(side=OrderSide.SELL, **common)  # type: ignore[arg-type]

    assert buy.base_size == sell.base_size
    assert buy.side is OrderSide.BUY
    assert sell.side is OrderSide.SELL


def test_a_closing_order_is_always_reduce_only() -> None:
    """Without it, a close that races the position -- a stop-out at the venue,
    a duplicate job -- opens a NEW position the other way instead of
    flattening the old one."""
    order = close_futures_order(
        side=OrderSide.SELL,
        client_order_id="abc",
        symbol="BTC_USDT_PERP",
        base_size=Decimal("0.0078"),
    )

    assert order.reduce_only is True
    assert order.base_size == Decimal("0.0078")


def test_a_closing_order_carries_no_leverage() -> None:
    """None derived its size, and reading one just to record it would let an
    account-settings call fail a close -- leaving a real position open."""
    order = close_futures_order(
        side=OrderSide.SELL,
        client_order_id="abc",
        symbol="BTC_USDT_PERP",
        base_size=Decimal("0.0078"),
    )

    assert order.leverage is None


def test_a_close_takes_its_size_verbatim_and_never_re_derives_it() -> None:
    """The ledger's number is the only honest one: fills happened at prices
    the alert never knew, in pieces, with fees. Re-deriving it from granted
    capital and a price is wrong by all three at once."""
    from_ledger = Decimal("0.00781234")

    order = close_futures_order(
        side=OrderSide.BUY,
        client_order_id="abc",
        symbol="BTC_USDT_PERP",
        base_size=from_ledger,
    )

    assert order.base_size == from_ledger


@pytest.mark.parametrize("base_size", [Decimal("0"), Decimal("-0.5")])
def test_an_order_with_no_size_is_unrepresentable(base_size: Decimal) -> None:
    with pytest.raises(InvariantViolation, match="base_size must be positive"):
        FuturesMarketOrder(
            client_order_id="abc",
            symbol="BTC_USDT_PERP",
            side=OrderSide.BUY,
            base_size=base_size,
            leverage=Decimal("5"),
        )


def test_an_order_with_no_leverage_is_unrepresentable() -> None:
    """Leverage travels with the order because it is what explains the
    position after the account setting moves. A zero would explain nothing."""
    with pytest.raises(InvariantViolation, match="leverage must be positive"):
        FuturesMarketOrder(
            client_order_id="abc",
            symbol="BTC_USDT_PERP",
            side=OrderSide.BUY,
            base_size=Decimal("0.01"),
            leverage=Decimal("0"),
        )


# ---- the protective stop's price (subscriber-safety SS.5) ----


@pytest.mark.parametrize(
    ("side", "entry", "tick", "expected"),
    [
        # Spec: "a live LONG opening built against 80.00 on a 0.01 tick" -> 72.00, and the
        # SHORT's stop is above it.
        (OrderSide.BUY, "80.00", "0.01", "72.00"),
        (OrderSide.SELL, "80.00", "0.01", "88.00"),
        # Off the tick, a LONG's level moves DOWN and a SHORT's UP: away from the entry,
        # never towards it, so the stop is never tighter than the author asked.
        (OrderSide.BUY, "80.03", "0.01", "72.02"),
        (OrderSide.SELL, "80.03", "0.01", "88.04"),
        # A small price, six places.
        (OrderSide.BUY, "0.066340", "0.000001", "0.059706"),
        (OrderSide.SELL, "0.066340", "0.000001", "0.072974"),
    ],
)
def test_the_stop_lies_ten_percent_away_on_the_tick_and_on_the_far_side(
    side: OrderSide, entry: str, tick: str, expected: str
) -> None:
    stop = protective_stop_price(
        side=side, entry=Decimal(entry), stop_loss_pct=Decimal("10"), tick=Decimal(tick)
    )

    assert str(stop) == expected


def test_the_stop_keeps_the_scale_of_the_tick_so_it_is_sent_as_the_spec_writes_it() -> None:
    stop = protective_stop_price(
        side=OrderSide.BUY,
        entry=Decimal("80"),
        stop_loss_pct=Decimal("10"),
        tick=Decimal("0.01"),
    )

    assert format(stop, "f") == "72.00"


def test_a_stop_that_rounds_to_nothing_is_refused_rather_than_sent() -> None:
    with pytest.raises(InvariantViolation, match="stop price must be positive"):
        protective_stop_price(
            side=OrderSide.BUY,
            entry=Decimal("0.5"),
            stop_loss_pct=Decimal("50"),
            tick=Decimal("1"),
        )


def test_an_opening_order_may_carry_a_stop_price_and_a_close_never_does() -> None:
    opening = FuturesMarketOrder(
        client_order_id="abc",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        base_size=Decimal("0.01"),
        leverage=Decimal("5"),
        stop_price=Decimal("72.00"),
    )
    assert opening.stop_price == Decimal("72.00")

    with pytest.raises(InvariantViolation, match="a reduce-only order carries no stop"):
        FuturesMarketOrder(
            client_order_id="abc",
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            base_size=Decimal("0.01"),
            reduce_only=True,
            stop_price=Decimal("72.00"),
        )


def test_the_orders_built_by_the_domain_carry_no_stop_unless_told() -> None:
    assert close_futures_order(
        side=OrderSide.SELL, client_order_id="abc", symbol="BTCUSDT", base_size=Decimal("1")
    ).stop_price is None

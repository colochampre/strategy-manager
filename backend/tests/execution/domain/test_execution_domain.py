"""Unit tests for ``ExecutionAttempt``/``MarketBuy``/``MarketSell``/``Fill``
(tasks.md 5.1).

Two rules are under test here, and they are not the same rule.

The old one: an order's size is never the alert's ``contracts`` field
(design.md § "Order size never comes from the alert").

The new one: a market order is denominated by side. A BUY spends a quote
amount — the granted capital, verbatim — and a SELL sells a base size derived
as ``granted / price``. The sum type exists so the wrong pairing cannot be
built at all, which is what the structural tests below actually assert.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import (
    MarketBuy,
    MarketSell,
    OrderSide,
    compute_order_quantity,
    market_order,
)
from strategy_manager.shared.domain.errors import InvariantViolation


def test_compute_order_quantity_divides_granted_by_price() -> None:
    granted = Decimal("200")
    price = Decimal("50000")

    quantity = compute_order_quantity(granted, price)

    assert quantity == Decimal("0.004")


def test_compute_order_quantity_ignores_the_alerts_contracts_field() -> None:
    """Structural proof, not just behavioural: the function signature has no
    ``contracts`` parameter at all, so it cannot leak in. A large,
    unrelated ``contracts`` value must have zero influence on the result."""

    granted = Decimal("200")
    price = Decimal("50000")
    alert_contracts = Decimal("999999")  # would dominate the result if ever used

    quantity = compute_order_quantity(granted, price)

    assert quantity == Decimal("0.004")
    assert quantity != alert_contracts


def test_compute_order_quantity_rejects_non_positive_price() -> None:
    with pytest.raises(InvariantViolation):
        compute_order_quantity(Decimal("200"), Decimal("0"))

    with pytest.raises(InvariantViolation):
        compute_order_quantity(Decimal("200"), Decimal("-1"))


def test_a_buy_carries_the_granted_amount_with_no_arithmetic_at_all() -> None:
    """The reservation granted 200 of the settlement currency, which IS the
    quote currency. Any transformation of that number here — division by a
    stale price, rounding to a base precision — would replace a figure the
    allocation engine decided with a worse one."""
    order = market_order(
        side=OrderSide.BUY,
        client_order_id="c1",
        symbol="BTC_USDT",
        granted=Decimal("200"),
        price=Decimal("50000"),
    )

    assert isinstance(order, MarketBuy)
    assert order.quote_amount == Decimal("200")
    assert order.side is OrderSide.BUY


def test_a_sell_carries_the_base_size_derived_from_the_price() -> None:
    order = market_order(
        side=OrderSide.SELL,
        client_order_id="c1",
        symbol="BTC_USDT",
        granted=Decimal("200"),
        price=Decimal("50000"),
    )

    assert isinstance(order, MarketSell)
    assert order.base_size == Decimal("0.004")
    assert order.side is OrderSide.SELL


def test_a_buy_cannot_be_built_carrying_a_base_size() -> None:
    """The point of the sum type. There is no field to put a base size in on a
    buy, so no adapter can send one — the venue rejects that combination, and
    here it cannot even be expressed."""
    assert not hasattr(
        MarketBuy(client_order_id="c1", symbol="BTC_USDT", quote_amount=Decimal("200")),
        "base_size",
    )
    assert not hasattr(
        MarketSell(client_order_id="c1", symbol="BTC_USDT", base_size=Decimal("1")),
        "quote_amount",
    )


def test_market_order_rejects_a_non_positive_price_on_either_side() -> None:
    """A sell needs the price arithmetically. A buy does not — but an alert
    quoting a price of zero is a malformed payload, and acting on a malformed
    payload is not made safe by the fact that this particular number happens
    to go unused."""
    for side in (OrderSide.BUY, OrderSide.SELL):
        with pytest.raises(InvariantViolation, match="price must be positive"):
            market_order(
                side=side,
                client_order_id="c1",
                symbol="BTC_USDT",
                granted=Decimal("200"),
                price=Decimal("0"),
            )


def test_an_order_rejects_a_non_positive_size() -> None:
    with pytest.raises(InvariantViolation, match="quote_amount"):
        MarketBuy(client_order_id="c1", symbol="BTC_USDT", quote_amount=Decimal("0"))

    with pytest.raises(InvariantViolation, match="base_size"):
        MarketSell(client_order_id="c1", symbol="BTC_USDT", base_size=Decimal("0"))


def test_fill_holds_exchange_reported_fields() -> None:
    filled_at = datetime(2026, 8, 18, tzinfo=UTC)

    fill = Fill(
        exchange_order_id="ex-order-1",
        exchange_fill_id="ex-fill-1",
        quantity=Decimal("0.004"),
        price=Decimal("50010"),
        fee=Decimal("0.01"),
        fee_currency="USDT",
        filled_at=filled_at,
    )

    assert fill.exchange_order_id == "ex-order-1"
    assert fill.exchange_fill_id == "ex-fill-1"
    assert fill.quantity == Decimal("0.004")
    assert fill.price == Decimal("50010")
    assert fill.fee == Decimal("0.01")
    assert fill.fee_currency == "USDT"
    assert fill.filled_at == filled_at


def test_execution_attempt_holds_its_fields() -> None:
    reservation_id = uuid4()
    attempt_id = uuid4()

    attempt = ExecutionAttempt(
        id=attempt_id,
        reservation_id=reservation_id,
        venue="spot",
        settlement_currency="USDT",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.004"),
        quote_amount=None,
        status=ExecutionStatus.SUBMITTED,
        client_order_id="c1",
    )

    assert attempt.id == attempt_id
    assert attempt.reservation_id == reservation_id
    assert attempt.status is ExecutionStatus.SUBMITTED
    assert attempt.exchange_order_id is None
    assert attempt.error is None


def test_an_attempt_carries_exactly_one_size() -> None:
    """Mirrors the ``ck_execution_attempts_one_size`` CHECK constraint, so the
    invalid row fails at construction instead of on the INSERT — and so the
    two representations can never disagree about what was sent."""
    def _attempt(quantity: Decimal | None, quote_amount: Decimal | None) -> None:
        ExecutionAttempt(
            id=uuid4(),
            reservation_id=uuid4(),
            venue="spot",
            settlement_currency="USDT",
            symbol="BTC_USDT",
            side=OrderSide.BUY,
            quantity=quantity,
            quote_amount=quote_amount,
            status=ExecutionStatus.SUBMITTED,
            client_order_id="c1",
        )

    with pytest.raises(InvariantViolation, match="exactly one size"):
        _attempt(None, None)

    with pytest.raises(InvariantViolation, match="exactly one size"):
        _attempt(Decimal("0.004"), Decimal("200"))

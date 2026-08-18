"""Unit tests for ``ExecutionAttempt``/``OrderRequest``/``Fill`` (tasks.md
5.1). The core assertion: order quantity is always derived as
``granted / price`` — ``granted`` is the reservation's already-decided
capital amount, never the alert's ``contracts`` field (design.md § "Order
size never comes from the alert").
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import (
    OrderRequest,
    OrderSide,
    compute_order_quantity,
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


def test_order_request_rejects_non_positive_quantity() -> None:
    with pytest.raises(InvariantViolation):
        OrderRequest(
            client_order_id="c1", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0")
        )


def test_order_request_holds_its_fields() -> None:
    order = OrderRequest(
        client_order_id="c1", symbol="BTCUSDT", side=OrderSide.BUY, quantity=Decimal("0.004")
    )

    assert order.client_order_id == "c1"
    assert order.symbol == "BTCUSDT"
    assert order.side is OrderSide.BUY
    assert order.quantity == Decimal("0.004")


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
        side=OrderSide.BUY,
        quantity=Decimal("0.004"),
        status=ExecutionStatus.SUBMITTED,
        client_order_id="c1",
    )

    assert attempt.id == attempt_id
    assert attempt.reservation_id == reservation_id
    assert attempt.status is ExecutionStatus.SUBMITTED
    assert attempt.exchange_order_id is None
    assert attempt.error is None

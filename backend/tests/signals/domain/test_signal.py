"""Unit tests for the WebhookSignal aggregate, IdempotencyKey VO and SignalStatus."""

from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal


def test_signal_status_values_match_db_constraint() -> None:
    assert SignalStatus.ACCEPTED == "ACCEPTED"
    assert SignalStatus.PROCESSING == "PROCESSING"
    assert SignalStatus.PROCESSED == "PROCESSED"
    assert SignalStatus.REJECTED == "REJECTED"


def test_idempotency_key_stores_its_value() -> None:
    key = IdempotencyKey("a" * 64)

    assert key.value == "a" * 64


def test_idempotency_key_rejects_empty_value() -> None:
    with pytest.raises(InvariantViolation):
        IdempotencyKey("")


def test_idempotency_key_rejects_value_over_200_chars() -> None:
    with pytest.raises(InvariantViolation):
        IdempotencyKey("a" * 201)


def test_webhook_signal_defaults_to_accepted_status_and_no_persisted_id() -> None:
    strategy_id = uuid4()

    signal = WebhookSignal(
        strategy_id=strategy_id,
        idempotency_key=IdempotencyKey("k" * 10),
        action="buy",
        contracts=Decimal("10"),
        position_size=Decimal("10"),
        price=Decimal("50000.5"),
        symbol="BTCUSDT",
        signal_type="a6a28229-9286-463f-99e8-5f48eb597d19",
        raw_payload={"symbol": "BTCUSDT"},
    )

    assert signal.strategy_id == strategy_id
    assert signal.status == SignalStatus.ACCEPTED
    assert signal.id is None
    assert signal.job_id is None
    assert signal.received_at is None


def test_webhook_signal_carries_typed_alert_fields_for_transition_reconstruction() -> None:
    signal = WebhookSignal(
        strategy_id=uuid4(),
        idempotency_key=IdempotencyKey("k" * 10),
        action="sell",
        contracts=Decimal("3.25"),
        position_size=Decimal("-3.25"),
        price=Decimal("0.001"),
        symbol="ETHUSDT",
        signal_type="a6a28229-9286-463f-99e8-5f48eb597d19",
        raw_payload={"symbol": "ETHUSDT"},
    )

    assert signal.action == "sell"
    assert signal.contracts == Decimal("3.25")
    assert signal.position_size == Decimal("-3.25")
    assert signal.price == Decimal("0.001")
    assert signal.symbol == "ETHUSDT"
    assert signal.signal_type == "a6a28229-9286-463f-99e8-5f48eb597d19"

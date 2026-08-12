"""Unit tests for TradingView alert parsing and idempotency-key derivation.

Covers the owner's real Pionex-format alert, adopted unchanged (design.md
§ "Alert Contract and Signal Routing").
"""

from decimal import Decimal

import pytest

from strategy_manager.signals.domain.alert import (
    AlertParsingError,
    TradingViewAlert,
    derive_idempotency_key,
)

VALID_PAYLOAD = {
    "data": {"action": "buy", "contracts": "10", "position_size": "10"},
    "price": "50000.5",
    "signal_param": "{}",
    "signal_type": "a6a28229-9286-463f-99e8-5f48eb597d19",
    "symbol": "BTCUSDT",
    "time": "2026-08-12T10:15:30Z",
}


def test_from_payload_parses_the_exact_pionex_format_alert() -> None:
    alert = TradingViewAlert.from_payload(VALID_PAYLOAD)

    assert alert.action == "buy"
    assert alert.contracts == Decimal("10")
    assert alert.position_size == Decimal("10")
    assert alert.price == Decimal("50000.5")
    assert alert.symbol == "BTCUSDT"
    assert alert.signal_type == "a6a28229-9286-463f-99e8-5f48eb597d19"
    assert alert.time == "2026-08-12T10:15:30Z"


def test_from_payload_coerces_string_numerics_to_decimal() -> None:
    payload = {
        **VALID_PAYLOAD,
        "data": {"action": "sell", "contracts": "3.25", "position_size": "-3.25"},
        "price": "0.001",
    }

    alert = TradingViewAlert.from_payload(payload)

    assert alert.contracts == Decimal("3.25")
    assert alert.position_size == Decimal("-3.25")
    assert alert.price == Decimal("0.001")


def test_from_payload_rejects_missing_data_object() -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "data"}

    with pytest.raises(AlertParsingError):
        TradingViewAlert.from_payload(payload)


def test_from_payload_rejects_malformed_data_object() -> None:
    payload = {**VALID_PAYLOAD, "data": "not-an-object"}

    with pytest.raises(AlertParsingError):
        TradingViewAlert.from_payload(payload)


def test_from_payload_rejects_non_string_numeric_field() -> None:
    payload = {
        **VALID_PAYLOAD,
        "data": {"action": "buy", "contracts": 10, "position_size": "10"},
    }

    with pytest.raises(AlertParsingError):
        TradingViewAlert.from_payload(payload)


def test_derive_idempotency_key_is_identical_for_identical_payloads() -> None:
    alert_a = TradingViewAlert.from_payload(VALID_PAYLOAD)
    alert_b = TradingViewAlert.from_payload(dict(VALID_PAYLOAD))

    assert derive_idempotency_key(alert_a) == derive_idempotency_key(alert_b)


def test_derive_idempotency_key_differs_when_position_size_differs_within_same_second() -> None:
    alert_a = TradingViewAlert.from_payload(VALID_PAYLOAD)
    alert_b = TradingViewAlert.from_payload(
        {**VALID_PAYLOAD, "data": {**VALID_PAYLOAD["data"], "position_size": "20"}}
    )

    assert derive_idempotency_key(alert_a) != derive_idempotency_key(alert_b)


def test_derive_idempotency_key_differs_when_contracts_differs_within_same_second() -> None:
    alert_a = TradingViewAlert.from_payload(VALID_PAYLOAD)
    alert_b = TradingViewAlert.from_payload(
        {**VALID_PAYLOAD, "data": {**VALID_PAYLOAD["data"], "contracts": "99"}}
    )

    assert derive_idempotency_key(alert_a) != derive_idempotency_key(alert_b)

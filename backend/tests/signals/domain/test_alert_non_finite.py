"""``TradingViewAlert.from_payload`` refuses a numeric field that is not finite.

Task 9qf.1. ``Decimal(value)`` accepts every spelling below without raising, so
the refusal has to be an explicit check in the one place that coerces the
alert's numbers. The exception is captured and asserted on, so a missing
refusal fails on an assertion rather than on whatever the unrefused value does
next.
"""

import copy
from typing import Any

import pytest

from strategy_manager.signals.domain.alert import AlertParsingError, TradingViewAlert

VALID_PAYLOAD: dict[str, Any] = {
    "data": {"action": "buy", "contracts": "10", "position_size": "10"},
    "price": "50000.5",
    "signal_param": "{}",
    "signal_type": "a6a28229-9286-463f-99e8-5f48eb597d19",
    "symbol": "BTCUSDT",
    "time": "2026-08-12T10:15:30Z",
}

FIELDS = ("price", "data.contracts", "data.position_size")
SPELLINGS = ("NaN", "nan", "sNaN", "Infinity", "-Infinity", "+Infinity", "inf", "Inf")


def _with(field: str, value: str) -> dict[str, Any]:
    payload = copy.deepcopy(VALID_PAYLOAD)
    target = payload["data"] if field.startswith("data.") else payload
    target[field.removeprefix("data.")] = value
    return payload


def _refusal(payload: dict[str, Any]) -> AlertParsingError | None:
    try:
        TradingViewAlert.from_payload(payload)
    except AlertParsingError as exc:
        return exc
    return None


@pytest.mark.parametrize("value", SPELLINGS)
@pytest.mark.parametrize("field", FIELDS)
def test_a_non_finite_number_is_refused_for_every_field_and_spelling(
    field: str, value: str
) -> None:
    refusal = _refusal(_with(field, value))

    assert refusal is not None
    assert field in str(refusal)


@pytest.mark.parametrize("value", SPELLINGS)
@pytest.mark.parametrize("field", FIELDS)
def test_the_refusal_never_echoes_the_raw_value(field: str, value: str) -> None:
    refusal = _refusal(_with(field, value))

    assert refusal is not None
    assert value not in str(refusal)


@pytest.mark.parametrize("field", FIELDS)
def test_a_finite_number_is_still_accepted_for_every_field(field: str) -> None:
    # Positive: a negative price is refused since 9qf.5 (the CHECK price > 0).
    assert _refusal(_with(field, "3.25")) is None

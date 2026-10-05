"""Every ``AlertParsingError`` carries a safe text for the log line.

Task 9qf.6. The 422 detail of some refusals carries the value the sender
supplied (``"{field} is not a valid decimal string: {value!r}"``), so it cannot
be logged as it is. Each refusal therefore carries a ``field`` and a fixed
``reason`` of its own, and ``log_text`` is built from those two alone.

The exception is captured and asserted on, so a refusal that has no log text
fails on an assertion rather than on an attribute error.
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

FIELDS = (
    "data.action",
    "data.contracts",
    "data.position_size",
    "price",
    "symbol",
    "signal_type",
    "time",
)
NUMERIC_FIELDS = ("data.contracts", "data.position_size", "price")
STRING_FIELDS = ("data.action", "symbol", "signal_type", "time")


def _container(payload: dict[str, Any], path: str) -> dict[str, Any]:
    return payload["data"] if path.startswith("data.") else payload


def _set(path: str, value: Any) -> dict[str, Any]:
    payload = copy.deepcopy(VALID_PAYLOAD)
    _container(payload, path)[path.removeprefix("data.")] = value
    return payload


def _without(path: str) -> dict[str, Any]:
    payload = copy.deepcopy(VALID_PAYLOAD)
    del _container(payload, path)[path.removeprefix("data.")]
    return payload


def _refusal(payload: Any) -> AlertParsingError | None:
    try:
        TradingViewAlert.from_payload(payload)
    except AlertParsingError as exc:
        return exc
    return None


def _log_text(payload: Any) -> str | None:
    refusal = _refusal(payload)
    assert refusal is not None
    return refusal.log_text


def test_a_payload_with_no_data_object_has_a_log_text() -> None:
    payload = copy.deepcopy(VALID_PAYLOAD)
    del payload["data"]

    assert _log_text(payload) == "data is missing or not an object"


def test_a_data_value_that_is_not_an_object_has_a_log_text_without_the_value() -> None:
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload["data"] = "MARKER-DATA"

    assert _log_text(payload) == "data is missing or not an object"


@pytest.mark.parametrize("field", FIELDS)
def test_a_missing_required_field_has_a_log_text_naming_it(field: str) -> None:
    assert _log_text(_without(field)) == f"{field} is missing"


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_a_number_that_is_not_a_string_has_a_log_text_without_the_number(field: str) -> None:
    text = _log_text(_set(field, 4242.4242))

    assert text == f"{field} is not a string"


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_a_string_that_is_not_a_decimal_has_a_log_text_without_the_string(field: str) -> None:
    text = _log_text(_set(field, "MARKER-DECIMAL"))

    assert text == f"{field} is not a valid decimal string"


@pytest.mark.parametrize("value", ["", 987654, None, ["buy"]])
@pytest.mark.parametrize("field", STRING_FIELDS)
def test_an_empty_or_non_string_text_field_has_a_log_text_without_the_value(
    field: str, value: Any
) -> None:
    assert _log_text(_set(field, value)) == f"{field} is empty or not a string"


def test_the_refusal_detail_that_echoes_the_value_is_unchanged() -> None:
    # Only the log text is safe; the 422 detail keeps its existing text.
    refusal = _refusal(_set("price", "MARKER-DECIMAL"))

    assert refusal is not None
    assert str(refusal) == "price is not a valid decimal string: 'MARKER-DECIMAL'"


def test_the_other_refusal_details_are_unchanged() -> None:
    assert str(_refusal(_without("price"))) == "payload is missing required field 'price'"
    assert str(_refusal(_without("data.action"))) == "payload is missing required field 'action'"
    assert str(_refusal(_set("price", 5))) == "price must be a string, got int"
    assert str(_refusal(_set("symbol", ""))) == "symbol must be a non-empty string"

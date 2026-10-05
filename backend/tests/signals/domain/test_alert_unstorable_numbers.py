"""``TradingViewAlert.from_payload`` refuses a number the ``signals`` table cannot hold.

Task 9qf.5. Migration 0002 declares ``price``, ``contracts`` and ``position_size``
as ``NUMERIC(38, 18)`` (20 digits before the point, 18 after) and puts exactly one
sign rule on them: the CHECK ``price > 0`` on the price. Nothing constrains the
sign of ``contracts`` or ``position_size``: a closing alert carries a
``position_size`` of zero and a short position may carry a negative one, so those
two fields keep accepting any finite number that fits the column.

Before this fix a value the column refused reached the insert, nothing caught
the refusal and the webhook answered an unhandled 500. The exception is captured
and asserted on, so a missing refusal fails on an assertion rather than on
whatever the unrefused value does next.
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
SIGNED_FIELDS = ("data.contracts", "data.position_size")

TWENTY_DIGITS = "99999999999999999999"
TWENTY_ONE_DIGITS = "100000000000000000000"
# Rounds to 10**20 at 18 decimals, so the column refuses it although its integer
# part has only 20 digits.
ROUNDS_UP_PAST_THE_COLUMN = "99999999999999999999.9999999999999999999"
# Rounds to zero at 18 decimals.
ROUNDS_DOWN_TO_ZERO = "0.0000000000000000001"
# 17,000 digits after the point: a display scale PostgreSQL cannot receive.
TOO_MANY_DECIMALS = "0." + "1" * 17000


def _with(field: str, value: str) -> dict[str, Any]:
    payload = copy.deepcopy(VALID_PAYLOAD)
    target = payload["data"] if field.startswith("data.") else payload
    target[field.removeprefix("data.")] = value
    return payload


def _refusal(payload: Any) -> AlertParsingError | None:
    try:
        TradingViewAlert.from_payload(payload)
    except AlertParsingError as exc:
        return exc
    return None


@pytest.mark.parametrize("value", ["0", "-1", "-0.5", "0.0", "-0", "0E+5", ROUNDS_DOWN_TO_ZERO])
def test_a_price_that_is_not_above_zero_is_refused(value: str) -> None:
    refusal = _refusal(_with("price", value))

    assert refusal is not None
    assert "price" in str(refusal)


@pytest.mark.parametrize("value", ["0", "-1", "-0.5", "-7123.5"])
def test_the_non_positive_price_refusal_never_echoes_the_value(value: str) -> None:
    refusal = _refusal(_with("price", value))

    assert refusal is not None
    assert value not in str(refusal)


@pytest.mark.parametrize("value", ["0.000000000000000001", "0.5", "50000.5", TWENTY_DIGITS])
def test_a_price_above_zero_that_the_column_holds_is_accepted(value: str) -> None:
    assert _refusal(_with("price", value)) is None


@pytest.mark.parametrize("value", ["0", "-1", "-0.5", "0.0", "-7123.5", ROUNDS_DOWN_TO_ZERO])
@pytest.mark.parametrize("field", SIGNED_FIELDS)
def test_contracts_and_position_size_carry_no_sign_rule_because_the_database_has_none(
    field: str, value: str
) -> None:
    assert _refusal(_with(field, value)) is None


@pytest.mark.parametrize(
    "value",
    [TWENTY_ONE_DIGITS, "1E+20", "-1E+20", "1E+999999", ROUNDS_UP_PAST_THE_COLUMN],
)
@pytest.mark.parametrize("field", FIELDS)
def test_a_number_with_more_integer_digits_than_the_column_holds_is_refused(
    field: str, value: str
) -> None:
    refusal = _refusal(_with(field, value))

    assert refusal is not None
    assert field in str(refusal)


@pytest.mark.parametrize(
    "value", ["0E+999999", "0E-999999", "1E-999999", "1E-20000", TOO_MANY_DECIMALS]
)
@pytest.mark.parametrize("field", SIGNED_FIELDS)
def test_a_number_whose_exponent_the_column_cannot_encode_is_refused(
    field: str, value: str
) -> None:
    # PostgreSQL's NUMERIC cannot receive a display scale above 16383, so such a
    # value (zero included) was refused at the insert although it is finite and,
    # for 1E-20000, smaller than the column's last decimal.
    refusal = _refusal(_with(field, value))

    assert refusal is not None
    assert field in str(refusal)


@pytest.mark.parametrize("value", ["0E+20", "0E+50", "1E-16000", "-1E-16000"])
@pytest.mark.parametrize("field", SIGNED_FIELDS)
def test_an_extreme_exponent_the_column_can_still_encode_is_accepted(
    field: str, value: str
) -> None:
    assert _refusal(_with(field, value)) is None


@pytest.mark.parametrize("value", [TWENTY_ONE_DIGITS, "1E+20", "1E+999999"])
@pytest.mark.parametrize("field", FIELDS)
def test_the_range_refusal_never_echoes_the_value(field: str, value: str) -> None:
    refusal = _refusal(_with(field, value))

    assert refusal is not None
    assert value not in str(refusal)


@pytest.mark.parametrize("value", [TWENTY_DIGITS, f"-{TWENTY_DIGITS}", "1E+19"])
@pytest.mark.parametrize("field", SIGNED_FIELDS)
def test_the_largest_number_the_column_holds_is_accepted(field: str, value: str) -> None:
    assert _refusal(_with(field, value)) is None


@pytest.mark.parametrize("payload", [[], [{"data": {}}], "alert", "", 5, 1.5, None, True])
def test_a_payload_that_is_not_an_object_is_refused(payload: Any) -> None:
    # Any exception is captured: today the parser raises AttributeError, and the
    # assertion below is what says it should be a refusal.
    failure: Exception | None = None
    try:
        TradingViewAlert.from_payload(payload)
    except Exception as exc:
        failure = exc

    assert isinstance(failure, AlertParsingError)
    assert "not a JSON object" in str(failure)

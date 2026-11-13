"""``StopLossPct``: a strategy's stop level, as a percentage of price (D5).

Mirrors ``ck_strategies_stop_loss_pct_range``: 1 to 50 inclusive, at most two
decimals."""

from decimal import Decimal

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.domain.stop_loss import DEFAULT_STOP_LOSS_PCT, StopLossPct


@pytest.mark.parametrize("value", ["1", "7.5", "10", "12.34", "50", "50.00"])
def test_a_level_from_one_to_fifty_with_two_decimals_is_taken(value: str) -> None:
    assert StopLossPct(Decimal(value)).value == Decimal(value)


@pytest.mark.parametrize("value", ["0.5", "0", "-1", "0.99", "50.01", "60", "NaN", "Infinity"])
def test_a_level_out_of_range_is_refused(value: str) -> None:
    with pytest.raises(InvariantViolation, match="1 to 50"):
        StopLossPct(Decimal(value))


@pytest.mark.parametrize("value", ["7.505", "10.001"])
def test_a_level_with_more_than_two_decimals_is_refused(value: str) -> None:
    with pytest.raises(InvariantViolation, match="two decimals"):
        StopLossPct(Decimal(value))


@pytest.mark.parametrize("value", [10, 7.5, "10", True])
def test_a_level_that_is_not_a_decimal_is_refused(value: object) -> None:
    with pytest.raises(InvariantViolation, match="Decimal"):
        StopLossPct(value)  # type: ignore[arg-type]


def test_the_level_offered_at_registration_is_ten() -> None:
    assert DEFAULT_STOP_LOSS_PCT == StopLossPct(Decimal("10"))

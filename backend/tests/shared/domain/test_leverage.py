"""``Leverage``: the leverage a user chose for one subscription (decision 38)."""

from decimal import Decimal

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.leverage import (
    MAX_LEVERAGE,
    NEW_SEAT_LEVERAGE,
    Leverage,
    max_leverage,
)


@pytest.mark.parametrize("value", [1, 2, 19, 20])
def test_a_leverage_from_one_to_twenty_is_taken(value: int) -> None:
    assert Leverage(value).value == value


@pytest.mark.parametrize("value", [0, -1, 21, 125])
def test_a_leverage_out_of_range_is_refused(value: int) -> None:
    with pytest.raises(InvariantViolation, match="1 to 20"):
        Leverage(value)


@pytest.mark.parametrize("value", [True, 2.0, "2"])
def test_a_leverage_that_is_not_an_integer_is_refused(value: object) -> None:
    with pytest.raises(InvariantViolation, match="integer"):
        Leverage(value)  # type: ignore[arg-type]


def test_the_cap_is_twenty_and_a_new_seat_starts_at_one() -> None:
    assert MAX_LEVERAGE == 20
    assert NEW_SEAT_LEVERAGE == Leverage(1)


@pytest.mark.parametrize(
    ("stop", "cap"),
    [
        ("10", 9),
        ("5", 16),
        ("1", 20),
        ("4", 20),
        ("4.76", 17),
        ("7.5", 11),
        ("15", 6),
        ("50", 1),
    ],
)
def test_the_cap_follows_the_stop_level(stop: str, cap: int) -> None:
    assert max_leverage(Decimal(stop)) == cap


def test_the_cap_never_passes_the_leverage_ceiling() -> None:
    assert max_leverage(Decimal("1")) == MAX_LEVERAGE

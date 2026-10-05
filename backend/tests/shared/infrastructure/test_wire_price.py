"""Unit tests: ``Price``, the wire type of a price that is a quotient (design.md,
addendum "a strategy's operations", sections B and D).

A price is rounded half-even to 18 places, the ledger's own scale, and written
in plain notation: a quotient such as ``notional / quantity`` can carry sixty
digits, and neither a JSON number nor an exponent may reach a client.
"""

from decimal import Decimal

import pytest
from pydantic import BaseModel

from strategy_manager.shared.infrastructure.wire import Price


class _Body(BaseModel):
    price: Price | None


def _written(value: Decimal) -> str | None:
    dumped = _Body(price=value).model_dump(mode="json")["price"]
    assert dumped is None or isinstance(dumped, str)
    return dumped


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0.4512"), "0.451200000000000000"),
        (Decimal("1"), "1.000000000000000000"),
        (Decimal("0.448"), "0.448000000000000000"),
        (Decimal("0.4512345678901234567891"), "0.451234567890123457"),
        (Decimal(1) / Decimal(3), "0.333333333333333333"),
        (Decimal(2) / Decimal(3), "0.666666666666666667"),
        (Decimal("123456789012345678901234567890.5"), (
            "123456789012345678901234567890.500000000000000000"
        )),
    ],
)
def test_a_price_is_rounded_half_even_to_18_places_in_plain_notation(
    value: Decimal, expected: str
) -> None:
    assert _written(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        Decimal("1E-7"),
        Decimal("1E-18"),
        Decimal("1E-30"),
        Decimal("1E+3"),
        Decimal("1.5E+30"),
        Decimal("0E-18"),
        Decimal("-0E-18"),
        Decimal(1) / Decimal(7),
    ],
)
def test_a_price_is_never_written_with_an_exponent(value: Decimal) -> None:
    written = _written(value)

    assert written is not None
    assert "e" not in written.lower()
    assert Decimal(written).is_finite()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # An exact tie at the 19th place goes to the even 18th digit.
        (Decimal("0.0000000000000000005"), "0.000000000000000000"),
        (Decimal("0.0000000000000000015"), "0.000000000000000002"),
        (Decimal("0.0000000000000000025"), "0.000000000000000002"),
        (Decimal("0.0000000000000000035"), "0.000000000000000004"),
        # Above the tie it goes up, below it goes down.
        (Decimal("0.000000000000000000501"), "0.000000000000000001"),
        (Decimal("0.000000000000000000499"), "0.000000000000000000"),
        # A tiny negative rounds to zero, which is written without a sign.
        (Decimal("-0.0000000000000000004"), "0.000000000000000000"),
    ],
)
def test_half_even_decides_at_the_nineteenth_place(value: Decimal, expected: str) -> None:
    assert _written(value) == expected

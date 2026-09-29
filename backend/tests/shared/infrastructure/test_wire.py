"""Unit tests: how the admin API writes numbers and instants
(``shared.infrastructure.wire``)."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from strategy_manager.shared.infrastructure.wire import Instant, Money, Ratio, plain, ratio


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0E-18"), "0.000000000000000000"),
        (Decimal("-0E-10"), "0.0000000000"),
        (Decimal("1E+2"), "100"),
        (Decimal("12.50"), "12.50"),
        (Decimal("-0.000000000000000001"), "-0.000000000000000001"),
        (Decimal("123456789012345678901234567890.123456789012345678"), (
            "123456789012345678901234567890.123456789012345678"
        )),
    ],
)
def test_plain_never_uses_an_exponent_and_never_writes_negative_zero(
    value: Decimal, expected: str
) -> None:
    assert plain(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("0.0094"), "0.0094000000"),
        (Decimal("0"), "0.0000000000"),
        (Decimal("-0.02"), "-0.0200000000"),
        # Half-even at the 10th place: ...5 rounds to the even neighbour.
        (Decimal("0.00000000025"), "0.0000000002"),
        (Decimal("0.00000000035"), "0.0000000004"),
        (Decimal("0.00000000015000001"), "0.0000000002"),
        # A tiny negative rounds to zero, which is written without a sign.
        (Decimal("-0.00000000001"), "0.0000000000"),
        (Decimal("1E+30"), "1000000000000000000000000000000.0000000000"),
    ],
)
def test_ratio_rounds_to_ten_places_half_even_in_plain_notation(
    value: Decimal, expected: str
) -> None:
    assert ratio(value) == expected


class _Body(BaseModel):
    amount: Money
    share: Ratio
    at: Instant


def test_money_ratio_and_instant_serialize_as_strings_and_utc() -> None:
    body = _Body(
        amount=Decimal("0E-18"),
        share=Decimal("0.0094"),
        at=datetime(2026, 9, 21, 14, 0, tzinfo=timezone(timedelta(hours=2))),
    )

    assert body.model_dump(mode="json") == {
        "amount": "0.000000000000000000",
        "share": "0.0094000000",
        "at": "2026-09-21T12:00:00Z",
    }
    assert body.at.tzinfo == UTC


def test_an_instant_without_a_time_zone_is_refused_not_assumed_to_be_utc() -> None:
    with pytest.raises(ValidationError, match="no time zone"):
        _Body(amount=Decimal(1), share=Decimal(1), at=datetime(2026, 9, 21, 12, 0))

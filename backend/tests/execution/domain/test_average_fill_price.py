"""``average_fill_price``: the entry a Binance stop is computed from (subscriber-safety SS.6).

An opening can fill in several pieces at several prices, and the stop lies a percentage away
from what the position actually cost, which is the volume-weighted average, not the first
fill and not the plain mean.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.execution.domain.fill import Fill, average_fill_price
from strategy_manager.shared.domain.errors import InvariantViolation


def _fill(quantity: str, price: str, fill_id: str = "1") -> Fill:
    return Fill(
        exchange_order_id="9",
        exchange_fill_id=fill_id,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("0"),
        fee_currency="USDT",
        filled_at=datetime(2026, 11, 13, tzinfo=UTC),
    )


def test_one_fill_averages_to_its_own_price() -> None:
    assert average_fill_price([_fill("76", "0.066340")]) == Decimal("0.066340")


def test_the_average_is_weighted_by_quantity_not_a_plain_mean() -> None:
    fills = [_fill("75", "100", "1"), _fill("25", "104", "2")]

    # (75 * 100 + 25 * 104) / 100 = 101, where the plain mean would say 102.
    assert average_fill_price(fills) == Decimal("101")


def test_no_fills_have_no_average() -> None:
    with pytest.raises(InvariantViolation):
        average_fill_price([])


def test_fills_of_no_quantity_have_no_average() -> None:
    with pytest.raises(InvariantViolation):
        average_fill_price([_fill("0", "100")])

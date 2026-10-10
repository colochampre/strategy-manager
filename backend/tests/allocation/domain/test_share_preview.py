"""Unit tests for ``share_amount`` and ``step_amounts``: what a share of a pool's
TOTAL asks for, and whether that is below the pool's minimum order (design.md, unit
12f addendum, sections C2 and C3; spec: admin-api "The Share Preview Route Serves The
Amount A Share Asks For"; tasks.md 12f.9.9).

The amount is NOT recomputed here: it is ``requested_from_percent``, the function the
worker sizes a request with, so every test compares with that function and not with a
second formula. ``below_pool_minimum`` is the comparison ``decide()`` makes first, and
one test runs the real ``decide()`` just under, at and just over the minimum.
"""

from decimal import Decimal

import pytest

from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.decision import SkipReason, decide
from strategy_manager.allocation.domain.percent import requested_from_percent
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.rules import AllocationRules, FillMode
from strategy_manager.allocation.domain.share_preview import share_amount, step_amounts
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue

_MINIMUM = Decimal("5")
_POOL = PoolKey(exchange=Exchange.BYBIT, venue=Venue.USDT_M, settlement_currency=Currency.USDT)


@pytest.mark.parametrize(
    ("total", "share", "written"),
    [
        ("333.33", "33.5", "111.665550000000000000"),
        ("10", "33.333333333333333333", "3.333333333333333333"),
        ("1000", "33.5", "335.000000000000000000"),
        ("1000", "0.0000001", "0.000001000000000000"),
        ("0.000000000000000001", "100", "0.000000000000000001"),
    ],
)
def test_the_amount_equals_requested_from_percent_for_a_table_of_totals_and_shares(
    total: str, share: str, written: str
) -> None:
    result = share_amount(Decimal(total), Decimal(share), _MINIMUM)

    assert result.amount == requested_from_percent(Decimal(total), Decimal(share))
    assert result.amount == Decimal(written)
    assert result.share == Decimal(share)


def test_the_amount_is_rounded_down_never_up() -> None:
    """2 * 33.3333333333333333335 / 100 is 0.66666666666666666667 exactly: the digit
    after the eighteenth place is a 6, which rounding to nearest would carry. The
    engine cuts, because rounding up is over-allocation."""
    result = share_amount(Decimal("2"), Decimal("33.3333333333333333335"), _MINIMUM)

    assert result.amount == Decimal("0.666666666666666666")


def test_the_amount_is_of_the_total_the_function_is_given() -> None:
    """Whatever else the pool holds, the amount follows the one total it is handed:
    the same share over 1000 and over 400 gives 100 and 40."""
    over_a_thousand = share_amount(Decimal("1000"), Decimal("10"), _MINIMUM)
    over_four_hundred = share_amount(Decimal("400"), Decimal("10"), _MINIMUM)

    assert over_a_thousand.amount == Decimal("100")
    assert over_four_hundred.amount == Decimal("40")


@pytest.mark.parametrize(
    ("total", "expected"), [("4.99", True), ("5.00", False), ("5.01", False)]
)
def test_below_pool_minimum_is_strictly_below(total: str, expected: bool) -> None:
    """A share of 100 asks for the whole total, so the total is the amount."""
    result = share_amount(Decimal(total), Decimal("100"), _MINIMUM)

    assert result.below_pool_minimum is expected


@pytest.mark.parametrize(
    ("total", "expected"), [("4.99", True), ("5.00", False), ("5.01", False)]
)
def test_below_pool_minimum_agrees_with_decide_just_under_at_and_just_over_the_minimum(
    total: str, expected: bool
) -> None:
    """The real ``decide()``, with a pool that has plenty free, skips a request as
    below the minimum for exactly the amount the preview flags."""
    previewed = share_amount(Decimal(total), Decimal("100"), _MINIMUM)
    decision = decide(
        CapitalPool(key=_POOL, balance=Decimal("1000"), reserved_active=Decimal("0")),
        Money(amount=previewed.amount, currency=Currency.USDT),
        AllocationRules(fill_mode=FillMode.PARTIAL, min_order_size=_MINIMUM),
    )

    skipped = decision.skip_reason is SkipReason.REQUEST_BELOW_MIN_ORDER_SIZE
    assert (previewed.below_pool_minimum, skipped) == (expected, expected)


def test_a_total_of_zero_gives_an_amount_of_zero_flagged_below_the_minimum() -> None:
    """The domain has a total to multiply, so a total of zero is an amount of zero,
    and zero is below any minimum. (The ROUTE serves no amount at all for a pool with
    no snapshot; this is a snapshot that reads zero.)"""
    result = share_amount(Decimal("0"), Decimal("33.5"), _MINIMUM)

    assert result.amount == Decimal("0")
    assert result.below_pool_minimum is True


def test_the_hundred_steps_are_numbered_one_to_a_hundred_and_each_equals_share_amount() -> None:
    total = Decimal("333.33")

    steps = step_amounts(total, _MINIMUM)

    assert [step.share for step in steps] == [Decimal(n) for n in range(1, 101)]
    assert list(steps) == [share_amount(total, Decimal(n), _MINIMUM) for n in range(1, 101)]

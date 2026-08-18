"""Unit tests for the pure ``decide()`` allocation function — all 6 ordered
rules and all 7 edge cases (spec: capital-allocation § Strategy Policy
Resolution, § Reservation Expiry; design.md § The AllocationDecision
Algorithm; tasks.md 4.1).
"""

from decimal import Decimal

from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.decision import (
    AllocationDecision,
    DecisionOutcome,
    SkipReason,
    decide,
)
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.rules import AllocationRules, FillMode
from strategy_manager.shared.domain.money import Currency, Money, Venue

_POOL_KEY = PoolKey(venue=Venue.SPOT, settlement_currency=Currency.USDT)


def _pool(balance: str, reserved_active: str) -> CapitalPool:
    return CapitalPool(
        key=_POOL_KEY, balance=Decimal(balance), reserved_active=Decimal(reserved_active)
    )


def _requested(amount: str) -> Money:
    return Money(amount=Decimal(amount), currency=Currency.USDT)


def _rules(fill_mode: FillMode, min_order_size: str = "10") -> AllocationRules:
    return AllocationRules(fill_mode=fill_mode, min_order_size=Decimal(min_order_size))


# --- rule 1: request itself below min order size --------------------------


def test_rule1_skips_when_request_is_below_min_order_size() -> None:
    pool = _pool(balance="1000", reserved_active="0")  # plenty of availability
    decision = decide(pool, _requested("5"), _rules(FillMode.PARTIAL, min_order_size="10"))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.SKIP,
        granted=Decimal("0"),
        skip_reason=SkipReason.REQUEST_BELOW_MIN_ORDER_SIZE,
    )


def test_rule1_short_circuits_before_availability_is_even_considered() -> None:
    """Edge case: request below min order size, checked before rule 2, even
    against a pool with zero availability."""
    pool = _pool(balance="0", reserved_active="0")
    decision = decide(pool, _requested("5"), _rules(FillMode.PARTIAL, min_order_size="10"))

    assert decision.skip_reason == SkipReason.REQUEST_BELOW_MIN_ORDER_SIZE


# --- rule 2: zero / negative availability ----------------------------------


def test_rule2_skips_on_zero_availability_balance_equals_reserved() -> None:
    pool = _pool(balance="1000", reserved_active="1000")
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.SKIP, granted=Decimal("0"), skip_reason=SkipReason.NO_AVAILABILITY
    )


def test_rule2_clamps_negative_availability_to_zero_never_a_negative_grant() -> None:
    """Edge case: reservations exceed the current balance (balance dropped)."""
    pool = _pool(balance="500", reserved_active="700")
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL))

    assert decision.outcome == DecisionOutcome.SKIP
    assert decision.skip_reason == SkipReason.NO_AVAILABILITY
    assert decision.granted == Decimal("0")


# --- rule 3: full allocation ------------------------------------------------


def test_rule3_full_allocation_when_requested_is_less_than_available() -> None:
    pool = _pool(balance="1000", reserved_active="0")
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.FULL, granted=Decimal("200"), skip_reason=None
    )


def test_rule3_full_allocation_when_requested_exactly_equals_available() -> None:
    """Edge case: requested == available drives availability to exactly 0."""
    pool = _pool(balance="1000", reserved_active="800")
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.FULL, granted=Decimal("200"), skip_reason=None
    )


# --- rule 4: skip fill mode under contention --------------------------------


def test_rule4_skip_fill_mode_skips_on_insufficient_availability() -> None:
    pool = _pool(balance="1000", reserved_active="900")  # available=100
    decision = decide(pool, _requested("200"), _rules(FillMode.SKIP))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.SKIP,
        granted=Decimal("0"),
        skip_reason=SkipReason.INSUFFICIENT_AVAILABILITY,
    )


# --- rule 5: partial fill mode but dust availability ------------------------


def test_rule5_skips_an_unfillable_dust_partial_below_min_order_size() -> None:
    """Edge case: availability below min order size under PARTIAL fill mode —
    an unfillable dust order is worse than a skip."""
    pool = _pool(balance="1000", reserved_active="995")  # available=5
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL, min_order_size="10"))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.SKIP,
        granted=Decimal("0"),
        skip_reason=SkipReason.PARTIAL_BELOW_MIN_ORDER_SIZE,
    )


# --- rule 6: partial allocation ---------------------------------------------


def test_rule6_partial_fill_grants_the_available_amount() -> None:
    pool = _pool(balance="1000", reserved_active="900")  # available=100
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL, min_order_size="10"))

    assert decision == AllocationDecision(
        outcome=DecisionOutcome.PARTIAL, granted=Decimal("100"), skip_reason=None
    )


# --- invariants --------------------------------------------------------------


def test_invariant_granted_never_exceeds_available_or_requested() -> None:
    pool = _pool(balance="1000", reserved_active="900")  # available=100
    decision = decide(pool, _requested("200"), _rules(FillMode.PARTIAL, min_order_size="10"))

    assert decision.granted <= pool.available
    assert decision.granted <= Decimal("200")


def test_invariant_granted_is_positive_iff_outcome_is_full_or_partial() -> None:
    full = decide(_pool("1000", "0"), _requested("200"), _rules(FillMode.PARTIAL))
    partial = decide(_pool("1000", "900"), _requested("200"), _rules(FillMode.PARTIAL))
    skip = decide(_pool("1000", "1000"), _requested("200"), _rules(FillMode.PARTIAL))

    assert full.outcome is DecisionOutcome.FULL and full.granted > 0
    assert partial.outcome is DecisionOutcome.PARTIAL and partial.granted > 0
    assert skip.outcome is DecisionOutcome.SKIP and skip.granted == 0

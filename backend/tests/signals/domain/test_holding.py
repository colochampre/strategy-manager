"""Unit tests for the Existing-Position Guard's domain value objects (spec:
capital-allocation § Existing-Position Guard; design.md's component
inventory § signals/domain/holding.py).

``classify_orphan`` is S4 scope and is deliberately not declared or tested
here.
"""

from decimal import Decimal
from uuid import uuid4

from strategy_manager.signals.domain.holding import HeldAllocation, OrphanKind, strategy_net


def test_held_allocation_carries_strategy_allocation_and_signed_net() -> None:
    strategy_id, allocation_id = uuid4(), uuid4()

    held = HeldAllocation(
        strategy_id=strategy_id, allocation_id=allocation_id, net_base=Decimal("0.5")
    )

    assert held.strategy_id == strategy_id
    assert held.allocation_id == allocation_id
    assert held.net_base == Decimal("0.5")


def test_held_allocation_net_base_can_be_negative_for_a_short() -> None:
    held = HeldAllocation(
        strategy_id=uuid4(), allocation_id=uuid4(), net_base=Decimal("-0.4")
    )

    assert held.net_base == Decimal("-0.4")


def test_orphan_kind_has_exactly_the_three_classification_outcomes() -> None:
    assert {kind.value for kind in OrphanKind} == {"REAL", "GHOST", "AMBIGUOUS"}


def test_strategy_net_sums_only_the_strategys_own_allocations() -> None:
    """The Existing-Position Guard is per strategy, not per pool -- a
    different strategy's holding on the same symbol must not be merged into
    this one's net (spec: capital-allocation § Existing-Position Guard)."""
    strategy_a, strategy_b = uuid4(), uuid4()
    holdings = [
        HeldAllocation(strategy_id=strategy_a, allocation_id=uuid4(), net_base=Decimal("0.5")),
        HeldAllocation(strategy_id=strategy_a, allocation_id=uuid4(), net_base=Decimal("0.2")),
        HeldAllocation(strategy_id=strategy_b, allocation_id=uuid4(), net_base=Decimal("9")),
    ]

    assert strategy_net(holdings, strategy_a) == Decimal("0.7")


def test_strategy_net_is_zero_when_the_strategy_holds_nothing() -> None:
    other = uuid4()
    holdings = [
        HeldAllocation(strategy_id=other, allocation_id=uuid4(), net_base=Decimal("0.3")),
    ]

    assert strategy_net(holdings, uuid4()) == Decimal("0")

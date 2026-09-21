"""Unit tests for the Existing-Position Guard's domain value objects (spec:
capital-allocation § Existing-Position Guard; design.md's component
inventory § signals/domain/holding.py).

``classify_orphan`` is S4 scope and is deliberately not declared or tested
here.
"""

from decimal import Decimal
from uuid import uuid4

from strategy_manager.signals.domain.holding import HeldAllocation, OrphanKind


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

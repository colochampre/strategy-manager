"""Unit tests for the Existing-Position Guard's domain value objects (spec:
capital-allocation § Existing-Position Guard; design.md's component
inventory § signals/domain/holding.py).

``classify_orphan`` (S4) is exercised over every row of design.md's
classification table, plus a venue-read failure.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.signals.domain.holding import (
    HeldAllocation,
    OrphanKind,
    classify_orphan,
    strategy_net,
)


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


# design.md § S4 — classification arithmetic. Every row of the nine-row
# table, verbatim: (l_s, l_p, v) -> expected OrphanKind. ``l_p`` is the
# pool's ledger net (summed over every strategy); ``v`` is the venue's
# reported net; ``O = l_p - l_s`` is derived inside ``classify_orphan``
# itself, never passed in -- there is no other strategy to attribute it to
# once the arithmetic is spelled out this way.
@pytest.mark.parametrize(
    ("l_s", "l_p", "v", "expected"),
    [
        pytest.param(
            Decimal("0.5"), Decimal("0.5"), Decimal("0.5"), OrphanKind.REAL,
            id="single-strategy-position-exists",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0.5"), Decimal("0"), OrphanKind.GHOST,
            id="closed-by-hand-or-liquidated",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0.5"), Decimal("0.3"), OrphanKind.AMBIGUOUS,
            id="partial-liquidation-is-ambiguous-not-real",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0.7"), Decimal("0.7"), OrphanKind.REAL,
            id="real-with-a-second-strategy-on-the-symbol",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0.7"), Decimal("0.2"), OrphanKind.GHOST,
            id="ghost-with-a-second-strategy",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0.7"), Decimal("0"), OrphanKind.AMBIGUOUS,
            id="both-legs-gone",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0"), Decimal("0"), OrphanKind.REAL,
            id="opposite-sides-netted-in-one-way-mode",
        ),
        pytest.param(
            Decimal("0.5"), Decimal("0"), Decimal("-0.5"), OrphanKind.GHOST,
            id="opposite-sides-netted-then-this-legs-gone",
        ),
        pytest.param(
            Decimal("0.2"), Decimal("0.4"), Decimal("0.2"), OrphanKind.GHOST,
            id="two-strategies-same-net-one-leg-gone",
        ),
    ],
)
def test_classify_orphan_over_every_design_table_row(
    l_s: Decimal, l_p: Decimal, v: Decimal, expected: OrphanKind
) -> None:
    assert classify_orphan(l_s, l_p, v) is expected


def test_classify_orphan_is_ambiguous_when_the_venue_read_failed() -> None:
    """``v=None`` is how a caller spells "the venue read timed out or
    failed" (design.md § S4; ``VenueNetPositionPort`` never raises). Exact
    Decimal arithmetic never gets a chance to misclassify what was never
    read."""
    assert classify_orphan(Decimal("0.5"), Decimal("0.5"), None) is OrphanKind.AMBIGUOUS

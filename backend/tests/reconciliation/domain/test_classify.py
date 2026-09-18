"""Unit tests for the pure ``classify()`` ladder (spec: reconciliation-scan
§ acceptance scenarios; design.md decision 7 -- the fixed verdict
precedence -- and decision 3 -- exact ``Decimal`` comparison).
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.reconciliation.domain.classify import classify
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.reconciliation.domain.positions import (
    LedgerPosition,
    OpenAllocation,
    VenuePosition,
)
from strategy_manager.shared.domain.errors import InvariantViolation


def _allocation(net_base: str) -> OpenAllocation:
    return OpenAllocation(allocation_id=uuid4(), net_base=Decimal(net_base))


def test_single_allocation_disagreement_is_attributable() -> None:
    """Spec: 'Single allocation disagreement is attributable' -- exactly one
    open allocation on BTCUSDT.P disagreeing with the venue."""
    venue = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("0.006"))
    ledger = LedgerPosition(symbol="BTCUSDT.P", open_allocations=(_allocation("0.004"),))

    assert classify(venue, ledger) == DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION


def test_multiple_allocations_with_a_partial_reduce_are_ambiguous() -> None:
    """Spec: 'Multiple allocations with a partial reduce are ambiguous' --
    two open allocations on SOLUSDT.P, venue quantity smaller than the
    ledger aggregate but non-zero."""
    venue = VenuePosition(symbol="SOLUSDT.P", net_base=Decimal("0.3"))
    ledger = LedgerPosition(
        symbol="SOLUSDT.P", open_allocations=(_allocation("0.3"), _allocation("0.4"))
    )

    assert classify(venue, ledger) == DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE


def test_venue_position_at_zero_with_several_allocations_is_attributable_full_close() -> None:
    """Spec: 'Venue position at zero with several allocations is
    attributable' -- two open allocations on SFPUSDT.P, venue exactly zero.
    One-way mode means the venue holds ONE net position per symbol, so a
    flat venue flattened every open allocation -- observation, not
    inference."""
    venue = VenuePosition(symbol="SFPUSDT.P", net_base=Decimal("0"))
    ledger = LedgerPosition(
        symbol="SFPUSDT.P", open_allocations=(_allocation("0.5"), _allocation("0.5"))
    )

    assert classify(venue, ledger) == DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE


def test_full_close_ladder_precedence_wins_over_single_allocation_when_both_fit() -> None:
    """design.md risk 3: with exactly ONE open allocation and a flat venue,
    both ATTRIBUTABLE_FULL_CLOSE and ATTRIBUTABLE_SINGLE_ALLOCATION are
    true; the ladder picks FULL_CLOSE, deliberately, because rung 2 (venue
    flat) is checked before rung 3 (exactly one open allocation)."""
    venue = VenuePosition(symbol="ETHUSDT.P", net_base=Decimal("0"))
    ledger = LedgerPosition(symbol="ETHUSDT.P", open_allocations=(_allocation("0.5"),))

    assert classify(venue, ledger) == DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE


def test_venue_position_the_ledger_never_knew_about_is_unmatched() -> None:
    """Spec: 'A venue position the ledger never knew about' -- the venue
    reports an open position with NO open allocation in that pool. Nothing
    is ever auto-attributed to it."""
    venue = VenuePosition(symbol="XRPUSDT.P", net_base=Decimal("100"))
    ledger = LedgerPosition(symbol="XRPUSDT.P", open_allocations=())

    assert classify(venue, ledger) == DiscrepancyKind.NO_MATCHING_ALLOCATION


def test_two_cancelling_allocations_are_ambiguous_not_unmatched() -> None:
    """Rung 1 tests the ABSENCE of allocations, not a zero net.

    Two allocations taking opposite sides of one symbol cancel to a zero
    ledger net while both remain open and attributable. Reading rung 1 as
    'ledger net is zero' would send this to NO_MATCHING_ALLOCATION and write
    a row claiming no allocation matched while carrying both of their ids in
    open_allocation_ids -- a row contradicting itself. They are ambiguous,
    not unattributable.
    """
    venue = VenuePosition(symbol="AAVEUSDT.P", net_base=Decimal("2"))
    ledger = LedgerPosition(
        symbol="AAVEUSDT.P", open_allocations=(_allocation("1.5"), _allocation("-1.5"))
    )

    assert ledger.net_base == Decimal("0")
    assert classify(venue, ledger) == DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE


def test_step_aligned_quantities_match_exactly_and_produce_no_discrepancy() -> None:
    """Spec: 'Step-aligned quantities match exactly' -- agreement produces
    no discrepancy at all, not a discrepancy with a zero delta."""
    venue = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("0.006"))
    ledger = LedgerPosition(symbol="BTCUSDT.P", open_allocations=(_allocation("0.006"),))

    assert classify(venue, ledger) is None


def test_both_sides_flat_produce_no_discrepancy() -> None:
    venue = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("0"))
    ledger = LedgerPosition(symbol="BTCUSDT.P", open_allocations=())

    assert classify(venue, ledger) is None


def test_short_side_single_allocation_disagreement_is_attributable() -> None:
    """Positions are signed -- short is negative. A short-side disagreement
    is classified exactly like a long one."""
    venue = VenuePosition(symbol="ETHUSDT.P", net_base=Decimal("-0.6"))
    ledger = LedgerPosition(symbol="ETHUSDT.P", open_allocations=(_allocation("-0.4"),))

    assert classify(venue, ledger) == DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION


def test_a_flat_venue_with_no_open_allocations_is_agreement_not_full_close() -> None:
    """Both sides at zero must not be misread as a full close: there is
    nothing open to have closed."""
    venue = VenuePosition(symbol="SOLUSDT.P", net_base=Decimal("0"))
    ledger = LedgerPosition(symbol="SOLUSDT.P", open_allocations=())

    assert classify(venue, ledger) is None


def test_comparison_is_exact_decimal_by_default_a_tiny_difference_is_still_a_discrepancy() -> None:
    """Design decision 3: exact comparison, ``tolerance`` defaults to zero."""
    venue = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("0.0060000001"))
    ledger = LedgerPosition(symbol="BTCUSDT.P", open_allocations=(_allocation("0.006"),))

    assert classify(venue, ledger) == DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION


def test_a_caller_supplied_tolerance_absorbs_a_small_difference() -> None:
    """The ``tolerance`` parameter is the forward door for a step-derived
    tolerance a future caller may pass in."""
    venue = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("0.0060000001"))
    ledger = LedgerPosition(symbol="BTCUSDT.P", open_allocations=(_allocation("0.006"),))

    assert classify(venue, ledger, tolerance=Decimal("0.000001")) is None


def test_in_flight_execution_attempt_symbols_are_still_classified_not_skipped() -> None:
    """Spec: 'In-flight execution attempt is still scanned' -- classify()
    takes no execution-attempt parameter at all, so there is no branch that
    could skip one; a symbol with an in-flight attempt is classified
    exactly like any other."""
    venue = VenuePosition(symbol="SOLUSDT.P", net_base=Decimal("0.5"))
    ledger = LedgerPosition(symbol="SOLUSDT.P", open_allocations=(_allocation("0.3"),))

    assert classify(venue, ledger) == DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION


def test_mismatched_symbols_raise_invariant_violation() -> None:
    venue = VenuePosition(symbol="BTCUSDT.P", net_base=Decimal("0.006"))
    ledger = LedgerPosition(symbol="ETHUSDT.P", open_allocations=(_allocation("0.006"),))

    with pytest.raises(InvariantViolation):
        classify(venue, ledger)

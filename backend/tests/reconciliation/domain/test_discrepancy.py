"""Unit tests for the discrepancy lifecycle rules (design.md decision 6;
spec: reconciliation-scan § consecutive-scan confirmation).
"""

from decimal import Decimal

from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
    derive_status,
    next_consecutive_scans,
)

_KIND = DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION


def _observation(
    kind: DiscrepancyKind = _KIND,
    venue_net_base: str = "0.5",
    ledger_net_base: str = "0.3",
) -> Observation:
    return Observation(
        kind=kind, venue_net_base=Decimal(venue_net_base), ledger_net_base=Decimal(ledger_net_base)
    )


def test_consecutive_scans_increments_when_the_observation_is_unchanged() -> None:
    previous = _observation()
    new = _observation()

    assert next_consecutive_scans(previous, new, previous_consecutive_scans=1) == 2


def test_consecutive_scans_keeps_climbing_across_more_unchanged_scans() -> None:
    previous = _observation()
    new = _observation()

    assert next_consecutive_scans(previous, new, previous_consecutive_scans=2) == 3


def test_consecutive_scans_resets_when_the_verdict_changes() -> None:
    previous = _observation(kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE)
    new = _observation(kind=DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION)

    assert next_consecutive_scans(previous, new, previous_consecutive_scans=2) == 1


def test_consecutive_scans_resets_when_venue_net_base_changes() -> None:
    previous = _observation(venue_net_base="0.5")
    new = _observation(venue_net_base="0.6")

    assert next_consecutive_scans(previous, new, previous_consecutive_scans=3) == 1


def test_consecutive_scans_resets_when_ledger_net_base_changes() -> None:
    previous = _observation(ledger_net_base="0.3")
    new = _observation(ledger_net_base="0.2")

    assert next_consecutive_scans(previous, new, previous_consecutive_scans=3) == 1


def test_consecutive_scans_resets_after_a_third_scan_that_differs() -> None:
    """Two consecutive matches climb to 3, then a differing third scan
    resets to 1 rather than continuing to climb (design decision 6)."""
    first = _observation()
    second = _observation()
    third = _observation(venue_net_base="0.9")

    after_second = next_consecutive_scans(first, second, previous_consecutive_scans=1)
    after_third = next_consecutive_scans(second, third, previous_consecutive_scans=after_second)

    assert after_second == 2
    assert after_third == 1


def test_consecutive_scans_treats_equal_decimal_value_as_unchanged_despite_different_scale() -> (
    None
):
    """``Decimal("1.0") == Decimal("1.00")`` is ``True``: the rule asks
    whether the disagreement moved, and a quantity that reads ``1.0`` then
    ``1.00`` did not move."""
    previous = _observation(venue_net_base="1.0")
    new = _observation(venue_net_base="1.00")

    assert next_consecutive_scans(previous, new, previous_consecutive_scans=1) == 2


def test_derive_status_is_observed_below_the_confirmation_threshold() -> None:
    status = derive_status(consecutive_scans=1, confirmations_required=2)

    assert status == DiscrepancyStatus.OBSERVED


def test_derive_status_is_confirmed_at_the_threshold() -> None:
    status = derive_status(consecutive_scans=2, confirmations_required=2)

    assert status == DiscrepancyStatus.CONFIRMED


def test_derive_status_is_confirmed_beyond_the_threshold() -> None:
    status = derive_status(consecutive_scans=3, confirmations_required=2)

    assert status == DiscrepancyStatus.CONFIRMED

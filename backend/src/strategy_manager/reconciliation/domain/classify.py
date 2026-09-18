"""Pure classification ladder (design.md's component inventory §
reconciliation/domain/classify.py; design decision 7; spec:
reconciliation-scan).

No framework imports, no I/O, no clock, no config — mirrors
``allocation.domain.decision.decide``'s pure-function shape exactly.
"""

from decimal import Decimal

from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from strategy_manager.reconciliation.domain.positions import LedgerPosition, VenuePosition
from strategy_manager.shared.domain.errors import InvariantViolation

_ZERO = Decimal("0")


def classify(
    venue: VenuePosition,
    ledger: LedgerPosition,
    tolerance: Decimal = _ZERO,
) -> DiscrepancyKind | None:
    """Evaluated strictly in order; the first matching rung wins (design.md
    decision 7's "fixed ladder", because two labels fitting one observation
    would oscillate and reset ``consecutive_scans`` forever).

    Returns ``None`` when the venue and the ledger agree within
    ``tolerance`` — agreement produces no discrepancy at all, not a
    discrepancy with a zero delta (spec: "Step-aligned quantities match
    exactly").

    ``tolerance`` defaults to exact ``Decimal`` equality (design decision 3).
    Reading the contract's ``qty_step`` here would add a per-symbol
    catalogue call to every scan; this parameter is the forward door for a
    step-derived tolerance a future caller may pass in. Any non-zero value
    MUST be derived from the symbol's own contract step size, never an
    arbitrarily chosen epsilon.

    There is deliberately no branch here for an in-flight execution
    attempt: a symbol with one in progress is classified exactly like any
    other, because skipping it is the failure this rule refuses to
    special-case (design.md decision 6's note on "the in-flight case the
    owner refused to handle by skipping").
    """

    if venue.symbol != ledger.symbol:
        raise InvariantViolation(
            f"symbol mismatch: venue={venue.symbol!r} ledger={ledger.symbol!r}"
        )

    delta = abs(venue.net_base - ledger.net_base)
    if delta <= tolerance:
        return None

    ledger_flat = ledger.net_base == _ZERO
    venue_flat = venue.net_base == _ZERO

    # Rung 1: NO allocation is open on the ledger, yet the venue reports a
    # position -- there is no allocation to attribute it to, and fabricating
    # one is worse than the problem.
    #
    # The test is the ABSENCE OF ALLOCATIONS, not a zero net. design.md's
    # ladder words this rung as "ledger flat", and the two are the same thing
    # right up until two allocations take opposite sides of one symbol and
    # cancel to zero. Then a zero net would send a symbol that HAS two
    # attributable allocations here, and the row would be written claiming no
    # allocation matched while carrying both of their ids in
    # open_allocation_ids -- a row contradicting itself. Cancelling
    # allocations are not unattributable, they are ambiguous, so they belong
    # at rung 4.
    if not ledger.open_allocations:
        return DiscrepancyKind.NO_MATCHING_ALLOCATION

    # Rung 2: the venue is flat but the ledger still has allocations open.
    # One-way (BUYSELL) mode means the venue holds exactly one net position
    # per symbol, so a flat venue flattened every open allocation on it --
    # this is observation, not inference. Checked BEFORE rung 3 on purpose:
    # with exactly one open allocation and a flat venue, both this rung and
    # rung 3 are true, and the ladder picks FULL_CLOSE here (design.md risk
    # 3). Any caller acting on ATTRIBUTABLE_FULL_CLOSE MUST treat it
    # identically to ATTRIBUTABLE_SINGLE_ALLOCATION, since this pairing is
    # the commonest case of all, not a rare edge.
    if venue_flat and not ledger_flat:
        return DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE

    # Rung 3: exactly one open allocation disagreeing with a non-flat venue.
    if len(ledger.open_allocations) == 1:
        return DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION

    # Rung 4: two or more open allocations share a non-flat, non-matching
    # venue position -- which one moved cannot be told from size alone.
    return DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE

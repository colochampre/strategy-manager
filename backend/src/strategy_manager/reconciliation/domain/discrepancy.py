"""Discrepancy vocabulary and lifecycle rules (design.md's component
inventory § reconciliation/domain/discrepancy.py; design decisions 6-7;
migration ``0020``'s CHECK constraints).

``DiscrepancyKind`` and ``DiscrepancyStatus`` mirror
``reconciliation_discrepancies.kind`` and ``.status`` exactly, the same way
``allocation.domain.rules.FillMode`` mirrors a CHECK constraint elsewhere:
these are the only strings that table will ever accept.

No framework imports, no I/O, no clock: ``first_observed_at`` /
``last_observed_at`` / ``confirmed_at`` are assigned by whoever writes the
row, not by this module.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class DiscrepancyKind(StrEnum):
    """The four verdicts of the classification ladder
    (``classify.classify()``). Mirrors ``ck_reconciliation_discrepancies_kind``."""

    ATTRIBUTABLE_SINGLE_ALLOCATION = "ATTRIBUTABLE_SINGLE_ALLOCATION"
    ATTRIBUTABLE_FULL_CLOSE = "ATTRIBUTABLE_FULL_CLOSE"
    AMBIGUOUS_PARTIAL_REDUCE = "AMBIGUOUS_PARTIAL_REDUCE"
    NO_MATCHING_ALLOCATION = "NO_MATCHING_ALLOCATION"


class DiscrepancyStatus(StrEnum):
    """Mirrors ``ck_reconciliation_discrepancies_status``. A row is written
    from scan 1 as ``OBSERVED``; it becomes ``CONFIRMED`` once
    ``consecutive_scans`` reaches the configured threshold. Only a
    ``CONFIRMED`` row is ever acted on (slice 2)."""

    OBSERVED = "OBSERVED"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True, slots=True)
class Observation:
    """What one scan found for one open discrepancy: the verdict and both
    quantities it was computed from. These three fields are exactly what
    design decision 6's "byte-identical" comparison checks — nothing else
    about a scan (its scan id, its timestamp) is part of "did the
    disagreement move"."""

    kind: DiscrepancyKind
    venue_net_base: Decimal
    ledger_net_base: Decimal


def next_consecutive_scans(
    previous: Observation, new: Observation, previous_consecutive_scans: int
) -> int:
    """Design decision 6: increments ONLY when ``new`` is identical to
    ``previous`` in kind and both quantities; any difference in any of the
    three is movement and resets the count to 1 — including a changing
    verdict, which is the in-flight case this rule refuses to special-case
    by skipping.

    Quantities are compared with ``Decimal`` value equality
    (``Decimal("1.0") == Decimal("1.00")`` is ``True`` despite differing
    string representations). That is the intended comparison here: the rule
    asks whether the disagreement MOVED, and a quantity that reads ``1.0``
    then ``1.00`` did not move — it is the same amount recomputed.
    """

    unchanged = (
        previous.kind == new.kind
        and previous.venue_net_base == new.venue_net_base
        and previous.ledger_net_base == new.ledger_net_base
    )
    if unchanged:
        return previous_consecutive_scans + 1
    return 1


def derive_status(consecutive_scans: int, confirmations_required: int) -> DiscrepancyStatus:
    """The threshold (``reconciliation_confirmations`` in config) is
    injected, never read from settings inside the domain."""

    if consecutive_scans >= confirmations_required:
        return DiscrepancyStatus.CONFIRMED
    return DiscrepancyStatus.OBSERVED

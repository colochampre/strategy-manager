"""The ``needs_owner`` rule: which open CONFIRMED discrepancies wait on the
owner and which are on their way to being booked without them (design.md's
PR 15 addendum § D; owner decision 66 Q3 and Q9, 2026-10-16).

One pure function sorts every open CONFIRMED discrepancy into exactly one of
three groups; an ``OBSERVED`` or a resolved row belongs to none. It reads the
confirmation STATE, never the presence of ``confirmed_at`` (which survives a
demotion), and compares observations by ``Decimal`` value.

No framework imports, no I/O, no clock: ``now`` and the grace are arguments.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.shared.domain.errors import InvariantViolation

_NEVER_BOOKABLE: frozenset[DiscrepancyKind] = frozenset(
    {DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE, DiscrepancyKind.NO_MATCHING_ALLOCATION}
)


class AttentionGroup(StrEnum):
    NEEDS_OWNER = "NEEDS_OWNER"
    BOOKED = "BOOKED"
    BEING_BOOKED = "BEING_BOOKED"


class NeedsOwnerReason(StrEnum):
    NOT_BOOKABLE = "NOT_BOOKABLE"
    SEVERAL_ALLOCATIONS = "SEVERAL_ALLOCATIONS"
    NOT_BOOKED = "NOT_BOOKED"
    REASON_UNKNOWN = "REASON_UNKNOWN"


@dataclass(frozen=True, slots=True)
class ConfirmedRow:
    """What the rule reads of one discrepancy row. ``status`` and ``resolved``
    come from the row; ``observation`` is its CURRENT kind and both nets;
    ``approved_observations`` are the observations frozen by every APPROVED
    proposal of that discrepancy."""

    status: DiscrepancyStatus
    resolved: bool
    observation: Observation
    open_allocation_count: int
    confirmed_at: datetime | None
    approved_observations: Sequence[Observation]


@dataclass(frozen=True, slots=True)
class Attention:
    group: AttentionGroup
    reason: NeedsOwnerReason | None = None


def sort_confirmed(row: ConfirmedRow, now: datetime, grace: timedelta) -> Attention | None:
    """The group (and, for NEEDS_OWNER, the reason) of ``row``, or ``None``
    when it is OBSERVED or resolved. Design § D, first match wins."""

    if row.status != DiscrepancyStatus.CONFIRMED or row.resolved:
        return None

    if row.observation.kind in _NEVER_BOOKABLE:
        return Attention(AttentionGroup.NEEDS_OWNER, NeedsOwnerReason.NOT_BOOKABLE)

    # ``Observation`` is a frozen dataclass: ``in`` compares kind and both
    # nets by value, so ``0.5`` and ``0.50`` are the same observation.
    if row.observation in row.approved_observations:
        return Attention(AttentionGroup.BOOKED)

    if row.open_allocation_count > 1:
        return Attention(AttentionGroup.NEEDS_OWNER, NeedsOwnerReason.SEVERAL_ALLOCATIONS)

    if row.confirmed_at is None:
        raise InvariantViolation("a CONFIRMED discrepancy carries no confirmed_at")
    if now - row.confirmed_at > grace:
        return Attention(AttentionGroup.NEEDS_OWNER, NeedsOwnerReason.NOT_BOOKED)

    return Attention(AttentionGroup.BEING_BOOKED)

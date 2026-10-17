"""T1: the pure ``needs_owner`` rule (design.md PR 15 addendum § D; spec "One
Pure Rule Sorts Every Open Confirmed Discrepancy By Who Must Act"; owner
decision 66 Q3 and Q9, 2026-10-16).

Table-driven: each kind x one or two allocations x booked on the current
observation x booked on a stale observation x unbooked inside and past the
grace x ``OBSERVED`` and resolved. No DB, no I/O.
"""

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from strategy_manager.reconciliation.domain import attention
from strategy_manager.reconciliation.domain.attention import (
    Attention,
    AttentionGroup,
    ConfirmedRow,
    NeedsOwnerReason,
    sort_confirmed,
)
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)

_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
_GRACE = timedelta(seconds=300)
_INSIDE = _NOW - timedelta(seconds=299)
_AT_GRACE = _NOW - _GRACE
_PAST = _NOW - timedelta(seconds=301)
_LONG_AGO = _NOW - timedelta(days=3)

_SINGLE = DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION
_FULL = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE
_AMBIGUOUS = DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE
_NO_MATCH = DiscrepancyKind.NO_MATCHING_ALLOCATION

_NEEDS = AttentionGroup.NEEDS_OWNER
_BOOKED = AttentionGroup.BOOKED
_BEING = AttentionGroup.BEING_BOOKED


def _observation(kind: DiscrepancyKind, venue: str = "0", ledger: str = "0.5") -> Observation:
    return Observation(kind=kind, venue_net_base=Decimal(venue), ledger_net_base=Decimal(ledger))


def _row(
    kind: DiscrepancyKind,
    *,
    allocations: int = 1,
    confirmed_at: datetime | None = _INSIDE,
    status: DiscrepancyStatus = DiscrepancyStatus.CONFIRMED,
    resolved: bool = False,
    approved: tuple[Observation, ...] = (),
) -> ConfirmedRow:
    return ConfirmedRow(
        status=status,
        resolved=resolved,
        observation=_observation(kind),
        open_allocation_count=allocations,
        confirmed_at=confirmed_at,
        approved_observations=approved,
    )


# The same nets as ``_observation`` spelled with different Decimal objects and
# exponents: equal by value, never the same object.
def _same_by_value(kind: DiscrepancyKind) -> Observation:
    return Observation(
        kind=kind, venue_net_base=Decimal("0.000"), ledger_net_base=Decimal("0.50")
    )


def _stale(kind: DiscrepancyKind) -> Observation:
    return Observation(kind=kind, venue_net_base=Decimal("0.1"), ledger_net_base=Decimal("0.5"))


_ROWS: list[tuple[str, ConfirmedRow, Attention | None]] = [
    # Rule 1: a kind that can never be booked needs the owner at once.
    (
        "ambiguous-inside-grace",
        _row(_AMBIGUOUS, confirmed_at=_INSIDE),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKABLE),
    ),
    (
        "ambiguous-past-grace",
        _row(_AMBIGUOUS, confirmed_at=_PAST),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKABLE),
    ),
    (
        "ambiguous-two-allocations",
        _row(_AMBIGUOUS, allocations=2),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKABLE),
    ),
    (
        "ambiguous-even-if-a-booking-matches",
        _row(_AMBIGUOUS, approved=(_same_by_value(_AMBIGUOUS),)),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKABLE),
    ),
    (
        "no-matching-inside-grace",
        _row(_NO_MATCH, allocations=0, confirmed_at=_INSIDE),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKABLE),
    ),
    (
        "no-matching-past-grace",
        _row(_NO_MATCH, allocations=0, confirmed_at=_PAST),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKABLE),
    ),
    # Rule 2: an APPROVED proposal froze the current observation (by value).
    (
        "single-booked-current",
        _row(_SINGLE, approved=(_same_by_value(_SINGLE),)),
        Attention(_BOOKED),
    ),
    (
        "single-booked-current-past-grace",
        _row(_SINGLE, confirmed_at=_PAST, approved=(_same_by_value(_SINGLE),)),
        Attention(_BOOKED),
    ),
    (
        "full-booked-current",
        _row(_FULL, approved=(_same_by_value(_FULL),)),
        Attention(_BOOKED),
    ),
    (
        "full-booked-current-two-allocations",
        _row(_FULL, allocations=2, approved=(_same_by_value(_FULL),)),
        Attention(_BOOKED),
    ),
    (
        "full-booked-current-among-an-older-one",
        _row(_FULL, approved=(_stale(_FULL), _same_by_value(_FULL))),
        Attention(_BOOKED),
    ),
    # A booking written, then the venue moved again (K row 12): not hidden.
    (
        "single-booked-stale-inside-grace",
        _row(_SINGLE, approved=(_stale(_SINGLE),)),
        Attention(_BEING),
    ),
    (
        "single-booked-stale-past-grace",
        _row(_SINGLE, confirmed_at=_PAST, approved=(_stale(_SINGLE),)),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED),
    ),
    (
        "full-booked-stale-past-grace",
        _row(_FULL, confirmed_at=_PAST, approved=(_stale(_FULL),)),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED),
    ),
    (
        "booked-for-another-kind-is-stale",
        _row(_FULL, confirmed_at=_PAST, approved=(_same_by_value(_SINGLE),)),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED),
    ),
    # Rule 3: more than one open allocation (Q9), inside or past the grace.
    (
        "full-two-allocations-inside-grace",
        _row(_FULL, allocations=2, confirmed_at=_INSIDE),
        Attention(_NEEDS, NeedsOwnerReason.SEVERAL_ALLOCATIONS),
    ),
    (
        "full-three-allocations-past-grace",
        _row(_FULL, allocations=3, confirmed_at=_PAST),
        Attention(_NEEDS, NeedsOwnerReason.SEVERAL_ALLOCATIONS),
    ),
    (
        "single-two-allocations-inside-grace",
        _row(_SINGLE, allocations=2, confirmed_at=_INSIDE),
        Attention(_NEEDS, NeedsOwnerReason.SEVERAL_ALLOCATIONS),
    ),
    # Rule 4: unbooked past the grace (Q3). Exactly at the grace is inside.
    (
        "single-unbooked-past-grace",
        _row(_SINGLE, confirmed_at=_PAST),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED),
    ),
    (
        "full-unbooked-past-grace",
        _row(_FULL, confirmed_at=_PAST),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED),
    ),
    (
        "full-unbooked-long-ago",
        _row(_FULL, confirmed_at=_LONG_AGO),
        Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED),
    ),
    (
        "single-unbooked-exactly-at-grace",
        _row(_SINGLE, confirmed_at=_AT_GRACE),
        Attention(_BEING),
    ),
    # Rule 5: otherwise, being booked.
    (
        "single-unbooked-inside-grace",
        _row(_SINGLE, confirmed_at=_INSIDE),
        Attention(_BEING),
    ),
    (
        "full-unbooked-inside-grace",
        _row(_FULL, confirmed_at=_INSIDE),
        Attention(_BEING),
    ),
    (
        "full-unbooked-just-confirmed",
        _row(_FULL, confirmed_at=_NOW),
        Attention(_BEING),
    ),
    # An OBSERVED or resolved row is in none of the groups. ``confirmed_at``
    # survives a demotion, so a stale timestamp must not matter.
    (
        "observed-single",
        _row(_SINGLE, status=DiscrepancyStatus.OBSERVED, confirmed_at=None),
        None,
    ),
    (
        "observed-after-demotion-with-old-confirmed-at",
        _row(_SINGLE, status=DiscrepancyStatus.OBSERVED, confirmed_at=_LONG_AGO),
        None,
    ),
    (
        "observed-ambiguous-with-old-confirmed-at",
        _row(_AMBIGUOUS, status=DiscrepancyStatus.OBSERVED, confirmed_at=_LONG_AGO),
        None,
    ),
    (
        "observed-two-allocations-with-old-confirmed-at",
        _row(_FULL, allocations=2, status=DiscrepancyStatus.OBSERVED, confirmed_at=_LONG_AGO),
        None,
    ),
    (
        "resolved-single",
        _row(_SINGLE, resolved=True, confirmed_at=_LONG_AGO),
        None,
    ),
    (
        "resolved-ambiguous",
        _row(_AMBIGUOUS, resolved=True, confirmed_at=_LONG_AGO),
        None,
    ),
    (
        "resolved-booked",
        _row(_FULL, resolved=True, approved=(_same_by_value(_FULL),)),
        None,
    ),
]


@pytest.mark.parametrize(
    ("row", "expected"),
    [pytest.param(row, expected, id=name) for name, row, expected in _ROWS],
)
def test_every_row_of_the_table_lands_in_its_group_with_its_reason(
    row: ConfirmedRow, expected: Attention | None
) -> None:
    assert sort_confirmed(row, _NOW, _GRACE) == expected


def test_a_row_confirmed_long_ago_demoted_and_confirmed_again_counts_at_once() -> None:
    # K row 12's sibling: ``confirmed_at`` survives a demotion (spec
    # "Confirmation State And Its Timestamp Are Not The Same Question"), so a
    # row confirmed again today still carries the old timestamp and is
    # NEEDS_OWNER at once. That is intended: it has been unbooked that long.
    row = _row(_FULL, confirmed_at=_LONG_AGO)

    assert sort_confirmed(row, _NOW, _GRACE) == Attention(_NEEDS, NeedsOwnerReason.NOT_BOOKED)


def test_the_domain_module_imports_no_framework() -> None:
    source = Path(attention.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported.isdisjoint({"fastapi", "sqlalchemy", "httpx"})

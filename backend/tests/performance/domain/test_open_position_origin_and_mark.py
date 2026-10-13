"""T8, ``origin_of`` and the discrepancy mark's key (design addendum "open
positions", sections D and E).

``origin_of`` must give the origin ``find_mismatches`` reports for the same two
flags, so the panel and the guard's refusal name an origin alike.

The mark's key is the ALLOCATION ID inside the POOL, on open ``CONFIRMED`` rows
only, with no origin filter and the market not a key. A stale confirmed row must
not mark a later position that happens to sit on the same market (K row 1).

A symbol is spelled differently on each side of the boundary (rule R7): the
ledger's fills as ``STXUSDT.P``, the discrepancy row as ``STXUSDT``.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.domain.mode_origin import Origin, find_mismatches
from strategy_manager.performance.domain.open_position import (
    DiscrepancyRow,
    PoolLabel,
    VenueDisagreement,
    origin_of,
    venue_disagreement_for,
)
from tests.performance.open_state_cases import open_element

# --- origin_of -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("rehearsal", "live", "dry_run", "expected"),
    [
        (True, True, True, Origin.MIXED),
        (True, True, False, Origin.MIXED),
        (True, False, False, Origin.REHEARSAL),
        (False, True, True, Origin.LIVE),
    ],
    ids=["both-seen-by-dry-run", "both-seen-by-live", "rehearsal-only", "live-only"],
)
def test_the_origin_is_the_one_the_guard_reports_for_the_same_flags(
    rehearsal: bool, live: bool, dry_run: bool, expected: Origin
) -> None:
    element = open_element(rehearsal=rehearsal, live=live)
    (mismatch,) = find_mismatches(dry_run=dry_run, open_allocations=[element], in_flight=[])

    assert mismatch.origin is expected  # the guard's own answer, as a premise
    assert origin_of(element) is mismatch.origin


@pytest.mark.parametrize(
    ("rehearsal", "live", "expected"),
    [
        (True, True, Origin.MIXED),
        (True, False, Origin.REHEARSAL),
        (False, True, Origin.LIVE),
        (False, False, Origin.LIVE),
    ],
    ids=["mixed", "rehearsal", "live", "neither-flag-is-live"],
)
def test_the_origin_comes_from_the_two_flags_and_nothing_else(
    rehearsal: bool, live: bool, expected: Origin
) -> None:
    assert origin_of(open_element(rehearsal=rehearsal, live=live)) is expected


# --- the mark's key --------------------------------------------------------------

POOL = PoolLabel("bybit", "usdt-m", "USDT")
OBSERVED_AT = datetime(2026, 10, 12, 11, 30, tzinfo=UTC)
A1 = uuid4()
A2 = uuid4()
A0 = uuid4()  # an allocation that is no longer open


def _row(
    *allocations: UUID,
    pool: PoolLabel = POOL,
    symbol: str = "STXUSDT",
    status: str = "CONFIRMED",
    resolved_at: datetime | None = None,
    observed_at: datetime = OBSERVED_AT,
    discrepancy_id: UUID | None = None,
    venue_net: str = "0",
    ledger_net: str = "0.82",
) -> DiscrepancyRow:
    return DiscrepancyRow(
        discrepancy_id=discrepancy_id or uuid4(),
        pool=pool,
        symbol=symbol,
        status=status,
        venue_net_base=Decimal(venue_net),
        ledger_net_base=Decimal(ledger_net),
        open_allocation_ids=tuple(allocations),
        last_observed_at=observed_at,
        resolved_at=resolved_at,
    )


def test_a_confirmed_row_naming_the_allocation_marks_it() -> None:
    row = _row(A1, discrepancy_id=UUID(int=7))

    assert venue_disagreement_for(A1, POOL, [row]) == VenueDisagreement(
        discrepancy_id=UUID(int=7),
        venue_net_base=Decimal("0"),
        ledger_net_base=Decimal("0.82"),
        allocation_count=1,
        last_observed_at=OBSERVED_AT,
    )


def test_a_row_of_the_same_market_naming_another_allocation_marks_nothing() -> None:
    """K row 1: A0 closed after the row was confirmed; a new position A1 sits on
    the same market. The allocation id cannot be inherited."""
    stale = _row(A0, symbol="STXUSDT")

    assert venue_disagreement_for(A1, POOL, [stale]) is None


def test_an_observed_row_marks_nothing() -> None:
    assert venue_disagreement_for(A1, POOL, [_row(A1, status="OBSERVED")]) is None


def test_a_resolved_row_marks_nothing() -> None:
    resolved = _row(A1, resolved_at=datetime(2026, 10, 12, 12, 0, tzinfo=UTC))

    assert venue_disagreement_for(A1, POOL, [resolved]) is None


@pytest.mark.parametrize(
    "other",
    [
        PoolLabel("binance", "usdt-m", "USDT"),
        PoolLabel("bybit", "spot", "USDT"),
        PoolLabel("bybit", "usdt-m", "USDC"),
    ],
    ids=["other-exchange", "other-venue", "other-currency"],
)
def test_a_row_of_another_pool_marks_nothing(other: PoolLabel) -> None:
    assert venue_disagreement_for(A1, POOL, [_row(A1, pool=other)]) is None


def test_a_row_naming_two_allocations_marks_both_and_says_so() -> None:
    row = _row(A1, A2, symbol="AAVEUSDT")

    first = venue_disagreement_for(A1, POOL, [row])
    second = venue_disagreement_for(A2, POOL, [row])

    assert first is not None
    assert second is not None
    assert (first.allocation_count, second.allocation_count) == (2, 2)
    assert first.discrepancy_id == second.discrepancy_id == row.discrepancy_id


def test_the_market_is_not_the_key() -> None:
    """The row's market is spelled as the venue spells it; the position's fills
    as the ledger does; a row naming the allocation under ANOTHER market still
    marks it (K row 12 logs the difference, in the use case)."""
    other_market = _row(A1, symbol="AAVEUSDT")

    assert venue_disagreement_for(A1, POOL, [other_market]) is not None


def test_no_row_at_all_marks_nothing() -> None:
    assert venue_disagreement_for(A1, POOL, []) is None


def test_the_mark_is_taken_from_the_matching_row_among_others() -> None:
    wrong_pool = _row(A1, pool=PoolLabel("binance", "usdt-m", "USDT"))
    observed = _row(A1, status="OBSERVED")
    stale = _row(A0)
    mine = _row(A1, A2, discrepancy_id=UUID(int=9))

    mark = venue_disagreement_for(A1, POOL, [wrong_pool, observed, stale, mine])

    assert mark is not None
    assert mark.discrepancy_id == UUID(int=9)
    assert mark.allocation_count == 2


def test_two_open_confirmed_rows_naming_one_allocation_give_the_latest_observed() -> None:
    """Stored data at fault, but the answer must not depend on the order the
    rows arrive in."""
    older = _row(A1, discrepancy_id=UUID(int=1), observed_at=OBSERVED_AT)
    newer = _row(
        A1, discrepancy_id=UUID(int=2), observed_at=datetime(2026, 10, 12, 11, 45, tzinfo=UTC)
    )

    for rows in ([older, newer], [newer, older]):
        mark = venue_disagreement_for(A1, POOL, rows)
        assert mark is not None
        assert mark.discrepancy_id == UUID(int=2)

"""``ReadConfirmed`` -- the application half of T8 (spec "Confirmed
Discrepancy Read Endpoint"; design.md PR 15 addendum § G; owner decision 66 Q5
and Q6, 2026-10-16; note N8).

Only fakes: the three ports are in memory. The route and the SQL behind it are
proven on real PostgreSQL in ``tests/reconciliation/infrastructure``.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application.auto_book_pending import AUTO_BOOKING_ACTOR
from strategy_manager.reconciliation.application.ports import (
    AllocationStrategy,
    ApprovedProposalSummary,
    DiscrepancyRecord,
    PoolKey,
)
from strategy_manager.reconciliation.application.read_confirmed import (
    BOOKED_LIMIT,
    ReadConfirmed,
)
from strategy_manager.reconciliation.domain.attention import NeedsOwnerReason
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind, DiscrepancyStatus

T0 = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
GRACE = 300
VENUE_NET = Decimal("0")
LEDGER_NET = Decimal("0.5")


class FixedClock:
    def now(self) -> datetime:
        return T0


def _row(
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
    confirmed_ago: int = GRACE + 60,
    allocations: Sequence[UUID] | None = None,
    symbol: str = "STXUSDT",
) -> DiscrepancyRecord:
    return DiscrepancyRecord(
        id=uuid4(),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=symbol,
        kind=kind,
        venue_net_base=VENUE_NET,
        ledger_net_base=LEDGER_NET,
        open_allocation_ids=tuple(allocations if allocations is not None else [uuid4()]),
        consecutive_scans=2,
        status=DiscrepancyStatus.CONFIRMED,
        first_observed_at=T0 - timedelta(seconds=confirmed_ago + 30),
        last_observed_at=T0,
        confirmed_at=T0 - timedelta(seconds=confirmed_ago),
        resolved_at=None,
        first_scan_id=uuid4(),
        last_scan_id=uuid4(),
        resolved_by_scan_id=None,
    )


def _proposal(
    discrepancy_id: UUID | None = None,
    decided_ago: timedelta = timedelta(hours=1),
    decided_by: str | None = AUTO_BOOKING_ACTOR,
    discrepancy_open: bool = True,
    observed: tuple[Decimal, Decimal] = (VENUE_NET, LEDGER_NET),
    allocation_id: UUID | None = None,
) -> ApprovedProposalSummary:
    return ApprovedProposalSummary(
        proposal_id=uuid4(),
        discrepancy_id=discrepancy_id or uuid4(),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="STXUSDT",
        kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        strategy_id=uuid4(),
        allocation_id=allocation_id or uuid4(),
        side="SELL",
        quantity=Decimal("0.5"),
        observed_venue_net_base=observed[0],
        observed_ledger_net_base=observed[1],
        fill_count=2,
        decided_at=T0 - decided_ago,
        decided_by=decided_by,
        execution_attempt_id=uuid4(),
        discrepancy_open=discrepancy_open,
    )


class FakeDiscrepancies:
    def __init__(self, rows: Sequence[DiscrepancyRecord]) -> None:
        self.rows = list(rows)

    async def list_discrepancies(
        self,
        pool: PoolKey | None = None,
        status: DiscrepancyStatus | None = None,
        open_only: bool = False,
    ) -> list[DiscrepancyRecord]:
        assert status is DiscrepancyStatus.CONFIRMED and open_only
        return list(self.rows)


class FakeProposals:
    """Honours the port's contract: decided at or after ``since``, or open."""

    def __init__(self, proposals: Sequence[ApprovedProposalSummary]) -> None:
        self.proposals = list(proposals)
        self.since: datetime | None = None

    async def approved_since(self, since: datetime) -> Sequence[ApprovedProposalSummary]:
        self.since = since
        return [p for p in self.proposals if p.decided_at >= since or p.discrepancy_open]


class FakeNames:
    def __init__(self, known: dict[UUID, AllocationStrategy] | None = None) -> None:
        self.known = known or {}
        self.asked: list[list[UUID]] = []

    async def strategies_for(
        self, allocation_ids: Sequence[UUID]
    ) -> dict[UUID, AllocationStrategy]:
        self.asked.append(list(allocation_ids))
        return {i: self.known[i] for i in allocation_ids if i in self.known}


def _use_case(
    rows: Sequence[DiscrepancyRecord] = (),
    proposals: Sequence[ApprovedProposalSummary] = (),
    names: FakeNames | None = None,
    dry_run: bool = False,
) -> tuple[ReadConfirmed, FakeProposals, FakeNames]:
    fake_proposals = FakeProposals(proposals)
    fake_names = names or FakeNames()
    use_case = ReadConfirmed(
        discrepancies=FakeDiscrepancies(rows),  # type: ignore[arg-type]
        proposals=fake_proposals,
        names=fake_names,
        clock=FixedClock(),
        grace_seconds=GRACE,
        dry_run=dry_run,
    )
    return use_case, fake_proposals, fake_names


async def test_the_three_lists_are_what_sort_confirmed_says() -> None:
    needs = _row(kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE)
    being = _row(confirmed_ago=10)
    booked_row = _row()
    stale_row = _row()  # confirmed past the grace and never booked
    proposal = _proposal(discrepancy_id=booked_row.id)
    use_case, _, _ = _use_case([needs, being, booked_row, stale_row], [proposal])

    reading = await use_case.read()

    assert [d.discrepancy_id for d in reading.needs_owner] == [needs.id, stale_row.id]
    assert [d.discrepancy_id for d in reading.being_booked] == [being.id]
    assert [b.proposal_id for b in reading.booked] == [proposal.proposal_id]
    assert reading.read_at == T0


async def test_needs_owner_count_equals_the_length_of_needs_owner() -> None:
    rows = [_row(kind=DiscrepancyKind.NO_MATCHING_ALLOCATION), _row(allocations=[uuid4(), uuid4()])]
    use_case, _, _ = _use_case(rows)

    reading = await use_case.read()

    assert len(reading.needs_owner) == 2
    assert reading.needs_owner_count == len(reading.needs_owner)


async def test_each_needs_owner_item_carries_the_reason_of_its_rule() -> None:
    not_bookable = _row(kind=DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE)
    several = _row(allocations=[uuid4(), uuid4()])
    not_booked = _row()
    use_case, _, _ = _use_case([not_bookable, several, not_booked])

    reading = await use_case.read()

    assert {d.discrepancy_id: d.reason for d in reading.needs_owner} == {
        not_bookable.id: NeedsOwnerReason.NOT_BOOKABLE,
        several.id: NeedsOwnerReason.SEVERAL_ALLOCATIONS,
        not_booked.id: NeedsOwnerReason.NOT_BOOKED,
    }


async def test_a_being_booked_item_has_no_reason() -> None:
    use_case, _, _ = _use_case([_row(confirmed_ago=10)])

    reading = await use_case.read()

    assert [d.reason for d in reading.being_booked] == [None]


async def test_a_discrepancy_booked_on_a_stale_observation_is_not_booked() -> None:
    row = _row(confirmed_ago=10)
    stale = _proposal(discrepancy_id=row.id, observed=(Decimal("0"), Decimal("0.9")))
    use_case, _, _ = _use_case([row], [stale])

    reading = await use_case.read()

    assert [d.discrepancy_id for d in reading.being_booked] == [row.id]


async def test_decided_by_is_automatic_for_the_worker_and_owner_for_anyone_else() -> None:
    automatic = _proposal(decided_by=AUTO_BOOKING_ACTOR, decided_ago=timedelta(hours=1))
    by_hand = _proposal(decided_by="admin", decided_ago=timedelta(hours=2))
    use_case, _, _ = _use_case(proposals=[automatic, by_hand])

    reading = await use_case.read()

    assert {b.proposal_id: b.decided_by for b in reading.booked} == {
        automatic.proposal_id: "automatic",
        by_hand.proposal_id: "owner",
    }


async def test_booked_is_newest_first_within_the_window_or_while_the_discrepancy_is_open() -> None:
    newest = _proposal(decided_ago=timedelta(days=1), discrepancy_open=False)
    middle = _proposal(decided_ago=timedelta(days=29), discrepancy_open=False)
    old_but_open = _proposal(decided_ago=timedelta(days=90), discrepancy_open=True)
    old_and_settled = _proposal(decided_ago=timedelta(days=31), discrepancy_open=False)
    use_case, fake, _ = _use_case(
        proposals=[old_but_open, middle, old_and_settled, newest],
    )

    reading = await use_case.read()

    assert fake.since == T0 - timedelta(days=30)
    assert [b.proposal_id for b in reading.booked] == [
        newest.proposal_id,
        middle.proposal_id,
        old_but_open.proposal_id,
    ]


async def test_booked_holds_at_most_one_hundred_newest_first() -> None:
    proposals = [_proposal(decided_ago=timedelta(minutes=i + 1)) for i in range(BOOKED_LIMIT + 20)]
    use_case, _, _ = _use_case(proposals=proposals)

    reading = await use_case.read()

    assert BOOKED_LIMIT == 100
    assert [b.proposal_id for b in reading.booked] == [
        p.proposal_id for p in proposals[:BOOKED_LIMIT]
    ]


async def test_names_are_asked_once_for_every_allocation_of_the_view() -> None:
    first, second = uuid4(), uuid4()
    row = _row(allocations=[first, second])
    proposal = _proposal(allocation_id=uuid4())
    use_case, _, names = _use_case([row], [proposal])

    await use_case.read()

    assert len(names.asked) == 1
    assert set(names.asked[0]) == {first, second, proposal.allocation_id}


async def test_allocations_and_bookings_carry_the_strategy_name() -> None:
    allocation, strategy = uuid4(), uuid4()
    row = _row(allocations=[allocation])
    proposal = _proposal(allocation_id=allocation)
    names = FakeNames({allocation: AllocationStrategy(strategy, "Trend A")})
    use_case, _, _ = _use_case([row], [proposal], names)

    reading = await use_case.read()

    [item] = reading.needs_owner
    assert [(a.allocation_id, a.strategy_id, a.strategy_name) for a in item.allocations] == [
        (allocation, strategy, "Trend A")
    ]
    [booking] = reading.booked
    assert booking.strategy_name == "Trend A"
    assert booking.strategy_id == proposal.strategy_id


async def test_a_missing_strategy_is_null_with_one_warning_naming_the_allocation_and_no_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    orphan = uuid4()
    row = _row(allocations=[orphan])
    use_case, _, _ = _use_case([row])

    with caplog.at_level(logging.DEBUG):
        reading = await use_case.read()

    [item] = reading.needs_owner
    [allocation] = item.allocations
    assert allocation.allocation_id == orphan
    assert allocation.strategy_id is None
    assert allocation.strategy_name is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(orphan) in warnings[0].getMessage()
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_a_booking_whose_strategy_is_missing_is_null_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proposal = _proposal()
    use_case, _, _ = _use_case(proposals=[proposal])

    with caplog.at_level(logging.DEBUG):
        reading = await use_case.read()

    [booking] = reading.booked
    assert booking.strategy_name is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(proposal.allocation_id) in warnings[0].getMessage()
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_dry_run_is_passed_through_and_the_lists_are_still_what_the_database_holds() -> None:
    use_case, _, _ = _use_case([_row(kind=DiscrepancyKind.NO_MATCHING_ALLOCATION)], dry_run=True)

    reading = await use_case.read()

    assert reading.dry_run is True
    assert len(reading.needs_owner) == 1


async def test_nothing_open_reads_nothing() -> None:
    use_case, _, names = _use_case()

    reading = await use_case.read()

    assert (reading.needs_owner, reading.being_booked, reading.booked) == ((), (), ())
    assert reading.needs_owner_count == 0
    assert all(asked == [] for asked in names.asked)

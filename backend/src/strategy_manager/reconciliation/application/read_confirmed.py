"""``ReadConfirmed``: the read behind the confirmed-discrepancies view
(design.md PR 15 addendum § G; owner decision 66 Q5 and Q6, 2026-10-16).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from strategy_manager.reconciliation.application.auto_book_pending import AUTO_BOOKING_ACTOR
from strategy_manager.reconciliation.application.confirmed_row import to_confirmed_row
from strategy_manager.reconciliation.application.ports import (
    ApprovedProposalsPort,
    DiscrepancyRecord,
    DiscrepancyRepositoryPort,
    StrategyNamesPort,
)
from strategy_manager.reconciliation.domain.attention import (
    AttentionGroup,
    NeedsOwnerReason,
    sort_confirmed,
)
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)

#: Q5: how far back settled bookings are listed, and how many at most.
BOOKED_WINDOW = timedelta(days=30)
BOOKED_LIMIT = 100


@dataclass(frozen=True, slots=True)
class AllocationView:
    allocation_id: UUID
    strategy_id: UUID | None
    strategy_name: str | None


@dataclass(frozen=True, slots=True)
class ConfirmedDiscrepancy:
    discrepancy_id: UUID
    # Whose discrepancy it is (multi-user AD10); the router turns it into the
    # user's e-mail for the admin's view.
    user_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    reason: NeedsOwnerReason | None
    venue_net_base: Decimal
    ledger_net_base: Decimal
    allocations: tuple[AllocationView, ...]
    confirmed_at: datetime | None
    last_observed_at: datetime


@dataclass(frozen=True, slots=True)
class BookedItem:
    proposal_id: UUID
    discrepancy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    strategy_id: UUID
    strategy_name: str | None
    allocation_id: UUID
    side: str
    quantity: Decimal
    fill_count: int
    decided_at: datetime
    decided_by: Literal["automatic", "owner"]
    execution_attempt_id: UUID | None
    discrepancy_open: bool


@dataclass(frozen=True, slots=True)
class ConfirmedReading:
    read_at: datetime
    dry_run: bool
    needs_owner: tuple[ConfirmedDiscrepancy, ...] = field(default_factory=tuple)
    being_booked: tuple[ConfirmedDiscrepancy, ...] = field(default_factory=tuple)
    booked: tuple[BookedItem, ...] = field(default_factory=tuple)

    @property
    def needs_owner_count(self) -> int:
        return len(self.needs_owner)


class ReadConfirmed:
    def __init__(
        self,
        discrepancies: DiscrepancyRepositoryPort,
        proposals: ApprovedProposalsPort,
        names: StrategyNamesPort,
        clock: ClockPort,
        grace_seconds: int,
        dry_run: bool,
    ) -> None:
        self._discrepancies = discrepancies
        self._proposals = proposals
        self._names = names
        self._clock = clock
        self._grace = timedelta(seconds=grace_seconds)
        self._dry_run = dry_run

    async def read(self) -> ConfirmedReading:
        """Three statements however many rows there are (the open CONFIRMED
        discrepancies, the APPROVED proposals, the strategies by allocation);
        no write, no lock. A fault in stored data is a WARNING, never an
        ERROR: the route is polled every 60 s per open tab (K row 13)."""

        now = self._clock.now()
        rows = await self._discrepancies.list_discrepancies(
            status=DiscrepancyStatus.CONFIRMED, open_only=True
        )
        proposals = await self._proposals.approved_since(now - BOOKED_WINDOW)

        # Rule 2 of design § D reads the observations frozen by EVERY APPROVED
        # proposal of an open discrepancy; the port answers all of them (an
        # open discrepancy is always in it), so no fourth statement is needed.
        open_ids = {row.id for row in rows}
        approved: dict[UUID, list[Observation]] = {}
        for proposal in proposals:
            if proposal.discrepancy_id in open_ids:
                approved.setdefault(proposal.discrepancy_id, []).append(
                    Observation(
                        proposal.kind,
                        proposal.observed_venue_net_base,
                        proposal.observed_ledger_net_base,
                    )
                )

        needing: list[tuple[DiscrepancyRecord, NeedsOwnerReason]] = []
        being: list[DiscrepancyRecord] = []
        for row in rows:
            attention = sort_confirmed(
                to_confirmed_row(row, approved.get(row.id, ())), now, self._grace
            )
            if attention is None or attention.group is AttentionGroup.BOOKED:
                continue
            if attention.group is AttentionGroup.NEEDS_OWNER and attention.reason is not None:
                needing.append((row, attention.reason))
            else:
                being.append(row)

        newest_first = sorted(proposals, key=lambda p: p.decided_at, reverse=True)
        booked = newest_first[:BOOKED_LIMIT]

        shown = [row for row, _ in needing] + being
        allocation_ids = {a for row in shown for a in row.open_allocation_ids}
        allocation_ids.update(p.allocation_id for p in booked)
        strategies = (
            await self._names.strategies_for(sorted(allocation_ids, key=str))
            if allocation_ids
            else {}
        )
        missing = sorted((a for a in allocation_ids if a not in strategies), key=str)
        if missing:
            logger.warning(
                "confirmed discrepancies view: no strategy found for allocation(s) %s; "
                "served with strategy_name null",
                ", ".join(str(a) for a in missing),
            )

        def view(row: DiscrepancyRecord, reason: NeedsOwnerReason | None) -> ConfirmedDiscrepancy:
            return ConfirmedDiscrepancy(
                discrepancy_id=row.id,
                user_id=row.user_id,
                exchange=row.exchange,
                venue=row.venue,
                settlement_currency=row.settlement_currency,
                symbol=row.symbol,
                kind=row.kind,
                reason=reason,
                venue_net_base=row.venue_net_base,
                ledger_net_base=row.ledger_net_base,
                allocations=tuple(
                    AllocationView(
                        a,
                        strategies[a].strategy_id if a in strategies else None,
                        strategies[a].name if a in strategies else None,
                    )
                    for a in row.open_allocation_ids
                ),
                confirmed_at=row.confirmed_at,
                last_observed_at=row.last_observed_at,
            )

        return ConfirmedReading(
            read_at=now,
            dry_run=self._dry_run,
            needs_owner=tuple(view(row, reason) for row, reason in needing),
            being_booked=tuple(view(row, None) for row in being),
            booked=tuple(
                BookedItem(
                    proposal_id=p.proposal_id,
                    discrepancy_id=p.discrepancy_id,
                    exchange=p.exchange,
                    venue=p.venue,
                    settlement_currency=p.settlement_currency,
                    symbol=p.symbol,
                    kind=p.kind,
                    strategy_id=p.strategy_id,
                    strategy_name=(
                        strategies[p.allocation_id].name if p.allocation_id in strategies else None
                    ),
                    allocation_id=p.allocation_id,
                    side=p.side,
                    quantity=p.quantity,
                    fill_count=p.fill_count,
                    decided_at=p.decided_at,
                    decided_by="automatic" if p.decided_by == AUTO_BOOKING_ACTOR else "owner",
                    execution_attempt_id=p.execution_attempt_id,
                    discrepancy_open=p.discrepancy_open,
                )
                for p in booked
            ),
        )

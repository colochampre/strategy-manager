"""``PrepareBooking``: freezes a booking proposal from a CONFIRMED
attributable discrepancy (design.md's component inventory
§ reconciliation/application/prepare_booking.py; design decisions 1, 5, 9,
11, 13, 16; spec: venue-close-booking, venue-reconciliation).

Sweeps every still-open CONFIRMED discrepancy of the two bookable kinds
(``BOOKABLE_KINDS``), fetches that market's venue fills for the window
``[first_observed_at - pad, now]``, matches the unrecorded ones against the
observed delta (``domain.booking.match_fills``), and FREEZES one
``booking_proposals`` row. Nothing here ever reaches ``ledger_entries`` or
``execution_attempts`` -- this use case's ports carry no reference to
either, and its only mutating call to ``BookingProposalRepositoryPort`` is
``insert``. ``mark_state`` (the ONLY method that can move a proposal past
PENDING or attach an ``execution_attempt_id``, per that port's own
docstring) belongs entirely to ``ApproveBooking``/``RejectBooking`` (Units
6a/6b) and is never called here.

**Deviation from design.md § 1/§ 16, flagged for the orchestrator.** Design
decision 11 describes the ``DRY_RUN`` hard skip as living "INSIDE the
handler" (``BookingPrepareHandler``, Unit 5), mirroring
``ReconciliationScanHandler``'s own skip. This unit's own binding
instructions and ``tasks.md``'s own test list
(``test_dry_run_hard_skip_no_fetch_no_proposal``) require it provable at
THIS use-case level too, with fakes only. ``PrepareBooking`` therefore takes
a required ``dry_run: bool`` constructor argument and refuses before any
read at all -- the same "refuse at BOTH the endpoint/handler AND the use
case" shape design decision 16 already prescribes for
``ApproveBooking``/``RejectBooking``. This does not remove Unit 5's own
handler-level skip; it is defense in depth, not a replacement.

Every symbol this module hands to a port or freezes onto a proposal is
``market_key()``-normalised, never trusted verbatim from the discrepancy row
or from a venue's echoed fill (design decision 13's testing rule: every
cross-boundary test uses a DIFFERENT spelling on each side). A fill whose
echoed market disagrees with the discrepancy's own refuses the WHOLE
proposal rather than silently dropping the odd fill -- an under-matched sum
would still refuse via ``match_fills``, but a fill quietly dropped before
that check could instead make an unrelated fill's quantity accidentally sum
to the delta.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from strategy_manager.reconciliation.application.market_key import market_key
from strategy_manager.reconciliation.application.ports import (
    AllocationOwnerPort,
    BookingProposalRepositoryPort,
    CommitPort,
    DiscrepancyRecord,
    DiscrepancyRepositoryPort,
    NewBookingProposal,
    PoolKey,
    ProposedFillSnapshot,
    RecordedFillIdsPort,
    VenueFill,
    VenueFillReaderRegistryPort,
    VenueFillReadError,
)
from strategy_manager.reconciliation.domain.booking import (
    BOOKABLE_KINDS,
    MatchRefused,
    ProposedFill,
    build_client_order_id,
    match_fills,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyStatus, Observation
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PrepareBookingResult:
    discrepancies_considered: int
    proposals_prepared: int
    proposals_skipped: int
    proposals_suppressed: int


class PrepareBooking:
    def __init__(
        self,
        discrepancies: DiscrepancyRepositoryPort,
        proposals: BookingProposalRepositoryPort,
        venue_fills: VenueFillReaderRegistryPort,
        recorded_fill_ids: RecordedFillIdsPort,
        allocation_owner: AllocationOwnerPort,
        clock: ClockPort,
        commit: CommitPort,
        window_pad_seconds: int,
        max_span_seconds: int,
        proposal_expiry_seconds: int,
        dry_run: bool,
    ) -> None:
        self._discrepancies = discrepancies
        self._proposals = proposals
        self._venue_fills = venue_fills
        self._recorded_fill_ids = recorded_fill_ids
        self._allocation_owner = allocation_owner
        self._clock = clock
        self._commit = commit
        self._window_pad = timedelta(seconds=window_pad_seconds)
        self._max_span = timedelta(seconds=max_span_seconds)
        self._proposal_expiry = timedelta(seconds=proposal_expiry_seconds)
        self._dry_run = dry_run

    async def sweep(self, job_id: UUID) -> PrepareBookingResult:
        if self._dry_run:
            logger.warning(
                "prepare booking: DRY_RUN is set, skipping the sweep entirely "
                "-- no venue fetch, no proposal"
            )
            return PrepareBookingResult(0, 0, 0, 0)

        now = self._clock.now()
        confirmed: Sequence[DiscrepancyRecord] = await self._discrepancies.list_discrepancies(
            status=DiscrepancyStatus.CONFIRMED, open_only=True
        )

        prepared = 0
        skipped = 0
        suppressed = 0
        considered = 0

        for discrepancy in confirmed:
            if discrepancy.kind not in BOOKABLE_KINDS:
                # AMBIGUOUS_PARTIAL_REDUCE / NO_MATCHING_ALLOCATION: never
                # bookable (design decision 14, spec's own requirement). The
                # database CHECK is the real guard; this is what keeps an
                # unbookable kind from ever reaching it.
                continue
            considered += 1

            observation = Observation(
                kind=discrepancy.kind,
                venue_net_base=discrepancy.venue_net_base,
                ledger_net_base=discrepancy.ledger_net_base,
            )
            if await self._proposals.has_matching_rejection(discrepancy.id, observation):
                logger.info(
                    "prepare booking: discrepancy %s suppressed -- a rejected "
                    "proposal already covers this exact observation",
                    discrepancy.id,
                )
                suppressed += 1
                continue

            expected_market = market_key(discrepancy.symbol)
            window_start = discrepancy.first_observed_at - self._window_pad
            span = now - window_start
            if span > self._max_span:
                logger.warning(
                    "prepare booking: discrepancy %s window span %s exceeds "
                    "the accepted maximum %s, refusing rather than fetching a "
                    "truncated window",
                    discrepancy.id,
                    span,
                    self._max_span,
                )
                skipped += 1
                continue

            pool: PoolKey = (
                discrepancy.exchange,
                discrepancy.venue,
                discrepancy.settlement_currency,
            )
            try:
                reader = self._venue_fills.for_pool(discrepancy.exchange, discrepancy.venue)
                fills = await reader.fills_in_window(pool, expected_market, window_start, now)
            except VenueFillReadError as exc:
                logger.warning(
                    "prepare booking: venue fill fetch failed for discrepancy "
                    "%s (%s), skipping this discrepancy: %s",
                    discrepancy.id,
                    expected_market,
                    exc,
                )
                skipped += 1
                continue

            mismatched = {
                market_key(fill.symbol)
                for fill in fills
                if market_key(fill.symbol) != expected_market
            }
            if mismatched:
                logger.warning(
                    "prepare booking: discrepancy %s expected market %s but "
                    "received fills for %s, refusing rather than silently "
                    "dropping the odd fill",
                    discrepancy.id,
                    expected_market,
                    sorted(mismatched),
                )
                skipped += 1
                continue

            recorded_ids = await self._recorded_fill_ids.recorded_fill_ids(
                discrepancy.exchange,
                discrepancy.venue,
                [fill.exchange_fill_id for fill in fills],
            )
            domain_fills = [_to_proposed_fill(fill) for fill in fills]
            delta_base = discrepancy.venue_net_base - discrepancy.ledger_net_base

            matched = match_fills(
                delta_base, domain_fills, recorded_ids, discrepancy.settlement_currency
            )
            if isinstance(matched, MatchRefused):
                logger.warning(
                    "prepare booking: discrepancy %s match refused (%s): %s",
                    discrepancy.id,
                    matched.reason,
                    matched.detail,
                )
                skipped += 1
                continue

            without_order_id = [
                fill.exchange_fill_id
                for fill in matched.fills
                if fill.exchange_order_id is None
            ]
            if without_order_id:
                # ledger_entries.exchange_order_id is NOT NULL, so ApproveBooking
                # could not write these fills. Proposing them would show the
                # owner a booking that fails when approved.
                logger.warning(
                    "prepare booking: discrepancy %s matched fills with no venue "
                    "order id %s, which the ledger cannot record; needs manual "
                    "reconciliation",
                    discrepancy.id,
                    sorted(without_order_id),
                )
                skipped += 1
                continue

            if not discrepancy.open_allocation_ids:
                raise InvariantViolation(
                    f"bookable discrepancy {discrepancy.id} carries no open allocation id"
                )
            if len(discrepancy.open_allocation_ids) > 1:
                # ATTRIBUTABLE_FULL_CLOSE fires for ANY number of open
                # allocations: a flat venue closed all of them. Booking the
                # whole close against one allocation would drive it negative
                # and leave the others open -- a permanent corruption of an
                # append-only ledger. Splitting it needs an invented FIFO or
                # pro-rata rule, which the owner ruled out, so it is refused.
                logger.warning(
                    "prepare booking: discrepancy %s closes %d open allocations "
                    "at once; one booking can attribute a close to exactly one "
                    "allocation, so this needs manual reconciliation",
                    discrepancy.id,
                    len(discrepancy.open_allocation_ids),
                )
                skipped += 1
                continue
            allocation_id = discrepancy.open_allocation_ids[0]
            strategy_id = await self._allocation_owner.strategy_for(allocation_id)
            client_order_id = build_client_order_id(discrepancy.exchange, matched.fills)

            proposal = NewBookingProposal(
                discrepancy_id=discrepancy.id,
                exchange=discrepancy.exchange,
                venue=discrepancy.venue,
                settlement_currency=discrepancy.settlement_currency,
                symbol=expected_market,
                kind=discrepancy.kind,
                allocation_id=allocation_id,
                strategy_id=strategy_id,
                side=matched.side,
                quantity=abs(delta_base),
                observed_venue_net_base=discrepancy.venue_net_base,
                observed_ledger_net_base=discrepancy.ledger_net_base,
                observed_allocation_ids=discrepancy.open_allocation_ids,
                fills=[_to_snapshot(fill) for fill in matched.fills],
                client_order_id=client_order_id,
                expires_at=now + self._proposal_expiry,
                prepared_by_job_id=job_id,
            )

            record = await self._proposals.insert(proposal)
            if record is None:
                # ``ux_booking_proposals_pending_per_discrepancy`` already
                # held a PENDING row for this discrepancy -- an expected,
                # non-raising outcome (design.md § 3's own idempotency
                # argument), not a second row and not an error.
                logger.info(
                    "prepare booking: discrepancy %s already holds a PENDING "
                    "proposal, not writing a second one",
                    discrepancy.id,
                )
                continue
            prepared += 1
            # Deliberately nothing further: the proposal is frozen PENDING
            # and stays that way until a human approves or rejects it
            # (``ApproveBooking``/``RejectBooking``, Units 6a/6b). Calling
            # ``mark_state`` here would be exactly the accidental
            # auto-approval the money-critical test in this unit exists to
            # catch.

        await self._commit.commit()
        return PrepareBookingResult(considered, prepared, skipped, suppressed)


def _to_proposed_fill(fill: VenueFill) -> ProposedFill:
    return ProposedFill(
        exchange_fill_id=fill.exchange_fill_id,
        exchange_order_id=fill.exchange_order_id,
        side=fill.side,
        quantity=fill.quantity,
        price=fill.price,
        fee=fill.fee,
        fee_currency=fill.fee_currency,
        filled_at=fill.filled_at,
    )


def _to_snapshot(fill: ProposedFill) -> ProposedFillSnapshot:
    return ProposedFillSnapshot(
        exchange_fill_id=fill.exchange_fill_id,
        exchange_order_id=fill.exchange_order_id,
        side=fill.side,
        quantity=fill.quantity,
        price=fill.price,
        fee=fill.fee,
        fee_currency=fill.fee_currency,
        filled_at=fill.filled_at,
    )

"""``ApproveBooking``: the FIRST reconciliation use case that writes to
``execution_attempts``/``ledger_entries`` (design.md's component inventory
§ reconciliation/application/approve_booking.py; design decisions 2, 4, 6,
7, 8, 14, 15, 16; spec: venue-close-booking, trade-execution, trade-ledger).

One transaction, in this exact order (design.md § 6):

1. ``proposals.get_for_update(id)`` -- row lock. Not PENDING ->
   ``ALREADY_DECIDED``, zero writes.
2. DRY_RUN -> refuse (``DRY_RUN_REFUSED``), also refused at the endpoint
   (Unit 7).
3. Expiry -> ``EXPIRED``. Freshness re-check (design.md § 7's (a)-(g), plus
   the single-allocation re-check design.md § 5 added) -> mismatch ->
   ``mark_state(SUPERSEDED)``.
4. ``usd_rate = usd_rates.usd_rate(Currency(settlement_currency))``,
   resolved in the same instant the row is inserted (design.md § 8).
5. ``BookingWritePort.write(attempt, fill_records)`` -> ``WRITTEN`` or
   ``ALREADY_RECORDED``.
6. ``WRITTEN`` -> ``mark_state(APPROVED, execution_attempt_id)``.
   ``ALREADY_RECORDED`` -> ``mark_state(SUPERSEDED, reason)`` + WARNING.
7. commit.

``mark_state`` returns whether it actually changed a row; a ``False`` here
is impossible under this use case's own row lock (the SAME transaction
holds it from ``get_for_update`` through to this call) and is therefore
raised as ``InvariantViolation`` rather than silently accepted -- a
caller-visible bug, never a swallowed race (review carryover, Units 6a/6b).
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.reconciliation.application.mark_state_guard import require_marked
from strategy_manager.reconciliation.application.ports import (
    BookingProposalRecord,
    BookingProposalRepositoryPort,
    BookingWriteOutcome,
    BookingWritePort,
    CommitPort,
    DiscrepancyRecord,
    DiscrepancyRepositoryPort,
    InFlightClosePort,
    PoolKey,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyStatus
from strategy_manager.shared.application.ports import ClockPort, UsdRateProviderPort
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency

logger = logging.getLogger(__name__)

_PENDING = "PENDING"
_APPROVED = "APPROVED"
_SUPERSEDED = "SUPERSEDED"
_EXPIRED = "EXPIRED"


class ApproveOutcome(StrEnum):
    """Every outcome ``ApproveBooking.approve`` can return. Exactly one of
    these, never a bare exception for an expected business outcome --
    mirrors ``SettleResult.status``'s own closed vocabulary."""

    APPROVED = "APPROVED"
    ALREADY_DECIDED = "ALREADY_DECIDED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DRY_RUN_REFUSED = "DRY_RUN_REFUSED"


@dataclass(frozen=True, slots=True)
class ApproveResult:
    outcome: ApproveOutcome
    proposal_id: UUID
    execution_attempt_id: UUID | None = None
    ledger_rows: int = 0
    reason: str | None = None


class ApproveBooking:
    def __init__(
        self,
        proposals: BookingProposalRepositoryPort,
        discrepancies: DiscrepancyRepositoryPort,
        in_flight_close: InFlightClosePort,
        writer: BookingWritePort,
        usd_rate_provider: UsdRateProviderPort,
        clock: ClockPort,
        commit: CommitPort,
        dry_run: bool,
    ) -> None:
        self._proposals = proposals
        self._discrepancies = discrepancies
        self._in_flight_close = in_flight_close
        self._writer = writer
        self._usd_rate_provider = usd_rate_provider
        self._clock = clock
        self._commit = commit
        self._dry_run = dry_run

    async def approve(self, proposal_id: UUID, decided_by: str) -> ApproveResult:
        proposal = await self._proposals.get_for_update(proposal_id)

        if proposal.state != _PENDING:
            logger.warning(
                "approve booking: proposal %s is no longer PENDING (state=%s) -- "
                "refusing as ALREADY_DECIDED, writing nothing",
                proposal.id,
                proposal.state,
            )
            await self._commit.commit()
            return ApproveResult(ApproveOutcome.ALREADY_DECIDED, proposal.id)

        if self._dry_run:
            logger.warning(
                "approve booking: DRY_RUN is set, refusing proposal %s -- no "
                "discrepancy re-read, no write, proposal stays PENDING",
                proposal.id,
            )
            await self._commit.commit()
            return ApproveResult(ApproveOutcome.DRY_RUN_REFUSED, proposal.id)

        now = self._clock.now()

        if proposal.expires_at <= now:
            changed = await self._proposals.mark_state(
                proposal.id,
                _EXPIRED,
                now,
                decided_by=decided_by,
                decision_reason="expired before approval",
            )
            require_marked(changed, proposal.id, _EXPIRED)
            logger.warning(
                "approve booking: proposal %s expired at %s (now %s) -- marking EXPIRED",
                proposal.id,
                proposal.expires_at,
                now,
            )
            await self._commit.commit()
            return ApproveResult(ApproveOutcome.EXPIRED, proposal.id)

        discrepancy = await self._discrepancies.get(proposal.discrepancy_id)
        mismatches = await self._freshness_mismatches(proposal, discrepancy)
        if mismatches:
            reason = "; ".join(mismatches)
            changed = await self._proposals.mark_state(
                proposal.id, _SUPERSEDED, now, decided_by=decided_by, decision_reason=reason
            )
            require_marked(changed, proposal.id, _SUPERSEDED)
            logger.warning(
                "approve booking: proposal %s is stale -- marking SUPERSEDED: %s",
                proposal.id,
                reason,
            )
            await self._commit.commit()
            return ApproveResult(ApproveOutcome.SUPERSEDED, proposal.id, reason=reason)

        usd_rate = await self._usd_rate_provider.usd_rate(
            Currency(proposal.settlement_currency)
        )
        attempt, fill_records = _build_write(proposal, usd_rate)
        write_result = await self._writer.write(attempt, fill_records)

        if write_result.outcome is BookingWriteOutcome.WRITTEN:
            changed = await self._proposals.mark_state(
                proposal.id,
                _APPROVED,
                now,
                decided_by=decided_by,
                execution_attempt_id=attempt.id,
            )
            require_marked(changed, proposal.id, _APPROVED)
            logger.info(
                "approve booking: proposal %s approved -- execution attempt %s, %d ledger rows",
                proposal.id,
                attempt.id,
                write_result.fills_written,
            )
            await self._commit.commit()
            return ApproveResult(
                ApproveOutcome.APPROVED,
                proposal.id,
                execution_attempt_id=attempt.id,
                ledger_rows=write_result.fills_written,
            )

        # ALREADY_RECORDED: the writer's SAVEPOINT already rolled back the
        # attempt-plus-fills write. The proposal is SUPERSEDED, never
        # re-tried and never double-booked.
        reason = f"already recorded ({write_result.reason})"
        changed = await self._proposals.mark_state(
            proposal.id, _SUPERSEDED, now, decided_by=decided_by, decision_reason=reason
        )
        require_marked(changed, proposal.id, _SUPERSEDED)
        logger.warning(
            "approve booking: proposal %s's write collided with an existing record "
            "(%s) -- marking SUPERSEDED, nothing double-booked",
            proposal.id,
            write_result.reason,
        )
        await self._commit.commit()
        return ApproveResult(ApproveOutcome.SUPERSEDED, proposal.id, reason=reason)

    async def _freshness_mismatches(
        self, proposal: BookingProposalRecord, discrepancy: DiscrepancyRecord
    ) -> list[str]:
        """design.md § 7's (a)-(g), by Decimal VALUE equality, plus the
        single-allocation re-check design.md § 5 added during apply. (h),
        the expiry branch, is checked separately by the caller because it
        produces a DIFFERENT outcome (``EXPIRED``, not ``SUPERSEDED``)."""

        mismatches: list[str] = []
        if discrepancy.resolved_at is not None:  # (a)
            mismatches.append(f"resolved_at is {discrepancy.resolved_at}, expected open")
        if discrepancy.status is not DiscrepancyStatus.CONFIRMED:  # (b)
            mismatches.append(f"status is {discrepancy.status}, expected CONFIRMED")
        if discrepancy.kind != proposal.kind:  # (c)
            mismatches.append(f"kind moved from {proposal.kind} to {discrepancy.kind}")
        if discrepancy.venue_net_base != proposal.observed_venue_net_base:  # (d)
            mismatches.append(
                f"venue_net_base moved from {proposal.observed_venue_net_base} to "
                f"{discrepancy.venue_net_base}"
            )
        if discrepancy.ledger_net_base != proposal.observed_ledger_net_base:  # (e)
            mismatches.append(
                f"ledger_net_base moved from {proposal.observed_ledger_net_base} to "
                f"{discrepancy.ledger_net_base}"
            )
        if tuple(sorted(discrepancy.open_allocation_ids)) != tuple(
            sorted(proposal.observed_allocation_ids)
        ):  # (f)
            mismatches.append(
                f"open_allocation_ids moved from {sorted(proposal.observed_allocation_ids)} "
                f"to {sorted(discrepancy.open_allocation_ids)}"
            )
        # design.md § 5's single-allocation rule, re-checked explicitly
        # against the discrepancy's CURRENT ``open_allocation_ids`` rather
        # than relying only on the array comparison above: the proposal's
        # own frozen ``allocation_id`` must still be the discrepancy's ONLY
        # open allocation. A second allocation appearing since prepare means
        # the close this proposal describes can no longer be attributed to
        # exactly one allocation, and must be refused rather than booked
        # against the one this proposal happens to name.
        if tuple(discrepancy.open_allocation_ids) != (proposal.allocation_id,):
            mismatches.append(
                f"allocation {proposal.allocation_id} is no longer the discrepancy's "
                f"only open allocation (now {list(discrepancy.open_allocation_ids)})"
            )
        pool: PoolKey = (proposal.exchange, proposal.venue, proposal.settlement_currency)
        if await self._in_flight_close.submitted_for(  # (g)
            pool, proposal.strategy_id, proposal.symbol
        ):
            mismatches.append(
                f"strategy {proposal.strategy_id} already has a SUBMITTED closing "
                f"attempt on {proposal.symbol}"
            )
        return mismatches


def _build_write(
    proposal: BookingProposalRecord, usd_rate: Decimal
) -> tuple[ExecutionAttempt, list[FillRecord]]:
    """design.md § 2, § 4, § 6: constructs the VENUE-origin attempt and its
    ledger rows from the proposal's FROZEN snapshot only -- the fills are
    never re-fetched, and ``client_order_id`` is never recomputed."""

    missing_order_ids = [
        fill.exchange_fill_id for fill in proposal.fills if fill.exchange_order_id is None
    ]
    if missing_order_ids:
        # design.md § 4: the tolerant window parser can, in principle,
        # produce a fill with no venue order id (a liquidation nobody has
        # yet observed -- tasks.md's live probe recorded item (d) as
        # UNKNOWN on both venues). ``ledger_entries.exchange_order_id`` is
        # NOT NULL (migration ``0005``) and ``FillRecord.exchange_order_id``
        # mirrors that, so there is no honest value to write here. Refusing
        # loudly is the only reading that does not put a placeholder into
        # an append-only ledger.
        raise InvariantViolation(
            f"proposal {proposal.id} carries fill(s) {missing_order_ids} with no venue "
            "order id -- ledger_entries.exchange_order_id is NOT NULL and this system "
            "has never observed this case (design.md § 4, probe item d); refusing "
            "rather than writing a placeholder"
        )

    attempt_id = uuid4()
    attempt = ExecutionAttempt(
        id=attempt_id,
        reservation_id=None,
        closes_allocation_id=proposal.allocation_id,
        exchange=proposal.exchange,
        venue=proposal.venue,
        settlement_currency=proposal.settlement_currency,
        symbol=proposal.symbol,
        side=OrderSide(proposal.side),
        quantity=proposal.quantity,
        quote_amount=None,
        leverage=None,
        status=ExecutionStatus.FILLED,
        origin=ExecutionOrigin.VENUE,
        client_order_id=proposal.client_order_id,
    )
    fill_records = [
        FillRecord(
            strategy_id=proposal.strategy_id,
            allocation_id=proposal.allocation_id,
            execution_attempt_id=attempt_id,
            exchange=proposal.exchange,
            venue=proposal.venue,
            settlement_currency=proposal.settlement_currency,
            symbol=proposal.symbol,
            side=fill.side,
            quantity=fill.quantity,
            price=fill.price,
            fee=fill.fee,
            fee_currency=fill.fee_currency,
            notional=fill.quantity * fill.price,
            exchange_order_id=cast(str, fill.exchange_order_id),
            exchange_fill_id=fill.exchange_fill_id,
            filled_at=fill.filled_at,
            usd_rate_at_fill=usd_rate,
        )
        for fill in proposal.fills
    ]
    return attempt, fill_records

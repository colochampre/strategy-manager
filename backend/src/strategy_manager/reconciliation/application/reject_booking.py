"""``RejectBooking``: rejects a PENDING proposal, writing ZERO rows anywhere
(design.md § 11 "Rejection semantics and suppression"; spec:
venue-close-booking's "Rejection Writes Nothing and Requires a Reason"
requirement).

One transaction, mirroring ``ApproveBooking``'s own order for the branches
they share:

1. ``proposals.get_for_update(id)`` -- row lock. Not PENDING ->
   ``ALREADY_DECIDED``, zero writes.
2. DRY_RUN -> refuse (``DRY_RUN_REFUSED``). Design.md § 16: reject refuses
   too -- under DRY_RUN no proposal can exist, so one that does means the
   mode changed under a live queue, and refusing both approve and reject is
   the only reading that does not act on state from the other mode.
3. A blank (after ``.strip()``) reason -> refuse (``REASON_REQUIRED``)
   BEFORE any write. Migration ``0023``'s own
   ``ck_booking_proposals_rejected_reason`` CHECK
   (``btrim(coalesce(decision_reason, '')) <> ''``) would refuse the same
   blank value at the database, but surfacing THAT as an unhandled
   ``IntegrityError`` would turn an expected business outcome into a crash
   -- this use case catches it first with the identical rule, so it always
   returns a typed outcome instead.
4. ``mark_state(REJECTED, decided_by=actor, decision_reason=reason)`` --
   its bool return is checked via the SAME shared guard
   ``ApproveBooking`` uses (``mark_state_guard.require_marked``), never a
   second copy of that check.
5. commit.

Unlike ``ApproveBooking``, this use case never re-reads the discrepancy and
never reaches ``BookingWritePort``: rejection is a statement about the
ATTRIBUTION this proposal proposed, not about the underlying disagreement,
so the discrepancy row is left completely untouched -- still OPEN, still
CONFIRMED, same Observation. A rejected-but-real discrepancy means the
ledger is knowingly wrong, which is exactly why the one WARNING this method
logs on a successful rejection names the proposal, the discrepancy it
belongs to, and the reason: it is the one place system-wide that admits the
ledger will keep disagreeing with the venue on purpose.

Suppression of a matching re-proposal is `PrepareBooking`'s own concern
(``has_matching_rejection``, Unit 4b, already implemented) -- this use case
never calls it and never needs to.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from strategy_manager.reconciliation.application.mark_state_guard import require_marked
from strategy_manager.reconciliation.application.ports import (
    BookingProposalRepositoryPort,
    CommitPort,
)
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)

_PENDING = "PENDING"
_REJECTED = "REJECTED"


class RejectOutcome(StrEnum):
    """Every outcome ``RejectBooking.reject`` can return -- mirrors
    ``ApproveOutcome``'s closed vocabulary, minus the outcomes only a write
    path can produce (``APPROVED``, ``SUPERSEDED``, ``EXPIRED``)."""

    REJECTED = "REJECTED"
    ALREADY_DECIDED = "ALREADY_DECIDED"
    DRY_RUN_REFUSED = "DRY_RUN_REFUSED"
    REASON_REQUIRED = "REASON_REQUIRED"


@dataclass(frozen=True, slots=True)
class RejectResult:
    outcome: RejectOutcome
    proposal_id: UUID
    reason: str | None = None


class RejectBooking:
    def __init__(
        self,
        proposals: BookingProposalRepositoryPort,
        clock: ClockPort,
        commit: CommitPort,
        dry_run: bool,
    ) -> None:
        self._proposals = proposals
        self._clock = clock
        self._commit = commit
        self._dry_run = dry_run

    async def reject(self, proposal_id: UUID, decided_by: str, reason: str) -> RejectResult:
        proposal = await self._proposals.get_for_update(proposal_id)

        if proposal.state != _PENDING:
            logger.warning(
                "reject booking: proposal %s is no longer PENDING (state=%s) -- "
                "refusing as ALREADY_DECIDED, writing nothing",
                proposal.id,
                proposal.state,
            )
            await self._commit.commit()
            return RejectResult(RejectOutcome.ALREADY_DECIDED, proposal.id)

        if self._dry_run:
            logger.warning(
                "reject booking: DRY_RUN is set, refusing proposal %s -- no write, "
                "proposal stays PENDING",
                proposal.id,
            )
            await self._commit.commit()
            return RejectResult(RejectOutcome.DRY_RUN_REFUSED, proposal.id)

        stripped_reason = reason.strip()
        if not stripped_reason:
            logger.warning(
                "reject booking: proposal %s rejected with a blank reason -- "
                "refusing before any write",
                proposal.id,
            )
            await self._commit.commit()
            return RejectResult(RejectOutcome.REASON_REQUIRED, proposal.id)

        now = self._clock.now()
        changed = await self._proposals.mark_state(
            proposal.id,
            _REJECTED,
            now,
            decided_by=decided_by,
            decision_reason=stripped_reason,
        )
        require_marked(changed, proposal.id, _REJECTED)
        logger.warning(
            "reject booking: proposal %s rejected for discrepancy %s -- reason: %s "
            "-- the discrepancy stays OPEN/CONFIRMED, the ledger is knowingly wrong",
            proposal.id,
            proposal.discrepancy_id,
            stripped_reason,
        )
        await self._commit.commit()
        return RejectResult(RejectOutcome.REJECTED, proposal.id, reason=stripped_reason)

"""``AutoBookPending``: approves every PENDING booking proposal in the worker's
own job, with the fixed actor ``system:auto-booking`` (design.md PR 15
addendum § C1; owner decision 66 Q1, 2026-10-16).

It depends on ``ApprovePort``, a ``Protocol`` with ``ApproveBooking.approve``'s
signature, never on the class. It writes nothing itself: every ledger write
stays inside ``ApproveBooking``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from uuid import UUID

from strategy_manager.reconciliation.application.approve_booking import ApproveOutcome
from strategy_manager.reconciliation.application.ports import (
    ApprovePort,
    BookingProposalRepositoryPort,
)
from strategy_manager.reconciliation.domain.booking import BookingRefusal

#: The ``decided_by`` actor of a booking the worker approves on its own
#: (owner decision 66 Q1, 2026-10-16), defined once. It lives in the
#: application layer so the worker side never imports the router module; the
#: router imports it from here.
AUTO_BOOKING_ACTOR = "system:auto-booking"

#: The two approval outcomes that mean "the proposal went stale" (design § E:
#: ``STALE_AT_APPROVAL`` for SUPERSEDED and EXPIRED). ``ALREADY_DECIDED`` is a
#: replay lost to another approver and ``DRY_RUN_REFUSED`` a configuration
#: state; neither is a refusal reason, both are only counted.
_STALE_OUTCOMES = frozenset({ApproveOutcome.SUPERSEDED, ApproveOutcome.EXPIRED})


@dataclass(frozen=True, slots=True)
class AutoBookResult:
    outcomes: Mapping[str, int] = field(default_factory=dict)
    """Count of proposals per ``ApproveOutcome`` value."""
    not_approved: Mapping[UUID, BookingRefusal] = field(default_factory=dict)
    """Discrepancy id -> code, for each proposal that was not approved."""
    approved: tuple[UUID, ...] = ()
    """The discrepancy ids whose proposal this run approved."""
    left_for_next_run: int = 0
    """How many PENDING proposals the list's limit left for the next run."""


class AutoBookPending:
    def __init__(
        self, proposals: BookingProposalRepositoryPort, approver: ApprovePort, limit: int = 100
    ) -> None:
        self._proposals = proposals
        self._approver = approver
        self._limit = limit

    async def run(self) -> AutoBookResult:
        # One row more than the limit is read, and never approved: its
        # presence is the only way to know the limit cut the list short, since
        # ``list_pending`` answers at most ``limit`` rows and offers no count.
        # So ``left_for_next_run`` is a lower bound (0 or 1), enough for the
        # handler's summary to say that the rest waits (design § C6).
        listed = await self._proposals.list_pending(limit=self._limit + 1)
        to_approve = listed[: self._limit]

        outcomes: dict[str, int] = {}
        not_approved: dict[UUID, BookingRefusal] = {}
        approved: list[UUID] = []

        # Deliberately no try/except around the call: an unexpected fault in
        # a ledger writer stops the writer rather than continuing past it
        # (design § C6). Every expected outcome is a returned value.
        for proposal in to_approve:
            result = await self._approver.approve(proposal.id, decided_by=AUTO_BOOKING_ACTOR)
            outcomes[result.outcome.value] = outcomes.get(result.outcome.value, 0) + 1
            if result.outcome is ApproveOutcome.APPROVED:
                approved.append(proposal.discrepancy_id)
            elif result.outcome in _STALE_OUTCOMES:
                not_approved[proposal.discrepancy_id] = BookingRefusal.STALE_AT_APPROVAL

        return AutoBookResult(
            outcomes=outcomes,
            not_approved=not_approved,
            approved=tuple(approved),
            left_for_next_run=len(listed) - len(to_approve),
        )

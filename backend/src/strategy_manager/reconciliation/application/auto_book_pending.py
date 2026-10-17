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

from strategy_manager.reconciliation.application.ports import (
    ApprovePort,
    BookingProposalRepositoryPort,
)
from strategy_manager.reconciliation.domain.booking import BookingRefusal


@dataclass(frozen=True, slots=True)
class AutoBookResult:
    outcomes: Mapping[str, int] = field(default_factory=dict)
    """Count of proposals per ``ApproveOutcome`` value."""
    not_approved: Mapping[UUID, BookingRefusal] = field(default_factory=dict)
    """Discrepancy id -> code, for each proposal that was not approved."""
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
        return AutoBookResult()

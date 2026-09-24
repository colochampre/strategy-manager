"""``ExpireBookingProposals``: marks every PENDING proposal whose frozen
``expires_at`` has passed as ``EXPIRED`` (design.md § 11 "Expiry"; spec:
venue-close-booking's "Proposal Expiry" requirement).

Runs inside ``BookingPrepareHandler``, BEFORE the sweep (design.md § 11's
own ordering), using the repository method Unit 3b already implemented --
``BookingProposalRepositoryPort.expire_pending`` -- so this use case is a
thin, single-purpose wrapper around one UPDATE, not a new write path. No new
repository method was needed for this unit.

Expiry is deliberately NOT a rejection. ``PrepareBooking.sweep``'s
suppression check (``has_matching_rejection``) only ever matches a
``REJECTED`` proposal's frozen Observation triple, never an ``EXPIRED``
one -- so a discrepancy whose proposal merely aged out, with nobody having
looked at it, is fully re-proposable on the very next sweep the moment it is
still CONFIRMED and unattributed. That is the behavioural difference this
unit's spec requirement names explicitly ("remains re-proposable on a later
scan"), and it falls out of `expire_pending` never touching
``has_matching_rejection``'s own REJECTED-only query -- nothing here needs
to special-case it.
"""

from dataclasses import dataclass

from strategy_manager.reconciliation.application.ports import (
    BookingProposalRepositoryPort,
    CommitPort,
)
from strategy_manager.shared.application.ports import ClockPort


@dataclass(frozen=True, slots=True)
class ExpireBookingProposalsResult:
    expired: int


class ExpireBookingProposals:
    def __init__(
        self,
        proposals: BookingProposalRepositoryPort,
        clock: ClockPort,
        commit: CommitPort,
    ) -> None:
        self._proposals = proposals
        self._clock = clock
        self._commit = commit

    async def expire(self) -> ExpireBookingProposalsResult:
        now = self._clock.now()
        count = await self._proposals.expire_pending(now)
        await self._commit.commit()
        return ExpireBookingProposalsResult(expired=count)

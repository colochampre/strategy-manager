"""Shared guard for ``BookingProposalRepositoryPort.mark_state``'s bool
return value (design.md's component inventory; review carryover, Units
6a/6b: "``mark_state`` returns bool; a False (lost race / not PENDING) MUST
become a caller-visible outcome, NEVER ignored").

``mark_state`` follows ``get_for_update`` in the same transaction, under the
row's own ``FOR UPDATE`` lock, in every use case that calls it
(``ApproveBooking``, ``RejectBooking``). A ``False`` return in that gap is
therefore impossible -- nothing else in this same transaction can move the
row out of ``PENDING`` between the two calls -- and is raised loudly rather
than silently accepted, exactly the shape ``ApproveBooking``'s own RED
evidence proved load-bearing (Unit 6a: removing ``get_for_update``'s ``FOR
UPDATE`` let a losing concurrent caller's ``mark_state`` genuinely return
``False`` under this same lock, and this guard is what turned that into a
loud, caller-visible bug instead of a swallowed race).

Both ``ApproveBooking`` and ``RejectBooking`` call THIS one function rather
than each keeping their own copy, per this unit's own binding instruction
not to duplicate a pattern that can be shared cleanly.
"""

from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation


def require_marked(changed: bool, proposal_id: UUID, state: str) -> None:
    if not changed:
        raise InvariantViolation(
            f"mark_state({state}) on proposal {proposal_id} changed no row despite "
            "this transaction holding its FOR UPDATE lock since get_for_update -- "
            "a bug elsewhere lost the row's PENDING state within this same "
            "transaction; never silently accepted (review carryover)"
        )

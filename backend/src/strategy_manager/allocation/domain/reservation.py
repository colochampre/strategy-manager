"""``Reservation`` aggregate and its legal state machine (design.md's
component inventory § allocation/domain/reservation.py; mirrors the
``reservations.status`` CHECK constraint from migration ``0004``).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.shared.domain.errors import InvariantViolation


class ReservationStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


# FILLED, RELEASED and EXPIRED are terminal: no further transition is legal.
_LEGAL_TRANSITIONS: dict[ReservationStatus, frozenset[ReservationStatus]] = {
    ReservationStatus.PENDING: frozenset(
        {ReservationStatus.SUBMITTED, ReservationStatus.RELEASED, ReservationStatus.EXPIRED}
    ),
    ReservationStatus.SUBMITTED: frozenset(
        {ReservationStatus.FILLED, ReservationStatus.RELEASED, ReservationStatus.EXPIRED}
    ),
    ReservationStatus.FILLED: frozenset(),
    ReservationStatus.RELEASED: frozenset(),
    ReservationStatus.EXPIRED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Reservation:
    """Mirrors a row of ``reservations`` (migration ``0004``)."""

    id: UUID
    strategy_id: UUID
    signal_id: UUID
    pool_key: PoolKey
    amount: Decimal
    status: ReservationStatus
    expires_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def transition_to(self, new_status: ReservationStatus) -> "Reservation":
        """Returns a new ``Reservation`` with the target status. Raises on any
        move not in ``_LEGAL_TRANSITIONS`` — illegal moves are a domain
        invariant violation, never a silent no-op."""

        if new_status not in _LEGAL_TRANSITIONS[self.status]:
            raise InvariantViolation(
                f"illegal reservation transition: {self.status} -> {new_status}"
            )
        return replace(self, status=new_status)

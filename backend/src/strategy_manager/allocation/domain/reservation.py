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


class ReleaseReason(StrEnum):
    """Why a reservation stopped holding capital. Recorded on the row so a
    terminal reservation says *how* it ended, not just *that* it did — the
    difference between a swept orphan and a deliberate abort is the whole
    signal when a worker starts misbehaving (migration ``0008``)."""

    EXPIRED_BY_SWEEPER = "EXPIRED_BY_SWEEPER"
    PRE_SUBMIT_EXPIRY = "PRE_SUBMIT_EXPIRY"
    EXCHANGE_ERROR = "EXCHANGE_ERROR"


# Only these two hold capital, so only these two are ever sweepable.
_SWEEPABLE_STATUSES: frozenset[ReservationStatus] = frozenset(
    {ReservationStatus.PENDING, ReservationStatus.SUBMITTED}
)


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
    terminal_at: datetime | None = None
    release_reason: ReleaseReason | None = None

    def transition_to(self, new_status: ReservationStatus) -> "Reservation":
        """Returns a new ``Reservation`` with the target status. Raises on any
        move not in ``_LEGAL_TRANSITIONS`` — illegal moves are a domain
        invariant violation, never a silent no-op."""

        if new_status not in _LEGAL_TRANSITIONS[self.status]:
            raise InvariantViolation(
                f"illegal reservation transition: {self.status} -> {new_status}"
            )
        return replace(self, status=new_status)

    def is_sweepable(self, now: datetime) -> bool:
        """Whether the expiry sweeper may give this reservation a terminal
        status. The boundary is inclusive: ``sum_active`` already stops counting
        a reservation once ``expires_at > now`` is false, so a row sitting
        exactly on its expiry is no longer holding capital and must be allowed
        to terminate."""

        return self.status in _SWEEPABLE_STATUSES and self.expires_at <= now

    def expire(self, now: datetime) -> "Reservation":
        """Terminates this reservation as swept. Raises if it already reached a
        terminal status — re-expiring a FILLED reservation would rewrite
        settled history, so it must never be a silent no-op."""

        return replace(
            self.transition_to(ReservationStatus.EXPIRED),
            terminal_at=now,
            release_reason=ReleaseReason.EXPIRED_BY_SWEEPER,
        )

"""``ExecutionAttempt`` DTO: mirrors a row of ``execution_attempts``
(migration ``0005``; design.md § execution/ and ledger/ (slice 5)).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.order import OrderSide


class ExecutionStatus(StrEnum):
    """Mirrors the ``execution_attempts.status`` CHECK constraint."""

    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    FAILED = "FAILED"
    ABORTED_EXPIRED = "ABORTED_EXPIRED"


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """One attempt to submit a reservation as an order. ``reservation_id`` is
    the reservation's ``allocation_id`` (spec: trade-execution §
    Reservation-Bound Submission)."""

    id: UUID
    reservation_id: UUID
    venue: str
    settlement_currency: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    status: ExecutionStatus
    client_order_id: str
    exchange_order_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

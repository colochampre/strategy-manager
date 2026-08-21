"""``ExecutionAttempt`` DTO: mirrors a row of ``execution_attempts``
(migrations ``0005`` and ``0011``; design.md § execution/ and ledger/
(slice 5)).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.domain.errors import InvariantViolation


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
    Reservation-Bound Submission).

    ``quantity`` and ``quote_amount`` mirror ``MarketSell``/``MarketBuy``:
    exactly one of them is set, and it is the number that actually went on
    the wire. Recording a base quantity for a buy would put a figure in the
    database that was never sent to anyone — derived from a stale alert price
    and impossible to reconcile against the exchange. What the order really
    filled at belongs to the ledger, which reads it from the fills.
    """

    id: UUID
    reservation_id: UUID
    venue: str
    settlement_currency: str
    symbol: str
    side: OrderSide
    quantity: Decimal | None
    quote_amount: Decimal | None
    status: ExecutionStatus
    client_order_id: str
    exchange_order_id: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Mirrors the ``ck_execution_attempts_one_size`` CHECK constraint, so
        the invariant fails at construction rather than on the INSERT."""
        if (self.quantity is None) == (self.quote_amount is None):
            raise InvariantViolation(
                "an ExecutionAttempt carries exactly one size: quantity for a "
                "sell (base) or quote_amount for a buy (quote)"
            )

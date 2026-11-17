"""``ExecutionAttempt`` DTO: mirrors a row of ``execution_attempts``
(migrations ``0005``, ``0011`` and ``0012``; design.md § execution/ and
ledger/ (slice 5)).
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


class ExecutionOrigin(StrEnum):
    """Mirrors the ``execution_attempts.origin`` CHECK constraint (migration
    ``0022``; design.md § 2).

    ``SYSTEM`` is every attempt this system itself submitted to a venue --
    ``PlaceOrder`` and ``ClosePosition``, both today. ``VENUE`` is an
    attempt this system never submitted: a booked close the venue reports,
    matched and approved through reconciliation's ``ApproveBooking``. The
    DB column defaults to ``SYSTEM`` for every pre-``0022`` row, but the
    Python field carries no default, so mypy forces every constructor to
    name it explicitly -- the DB default makes the migration one statement,
    the missing Python default is the discipline the DB default cannot
    provide.
    """

    SYSTEM = "SYSTEM"
    VENUE = "VENUE"


class ExecutionCause(StrEnum):
    """Mirrors the ``execution_attempts.cause`` CHECK constraint (migration ``0043``):
    what asked for the attempt.

    ``SIGNAL``: a strategy's signal, an opening or the close it asked for. ``STOP``: a
    protective stop that fired at the venue, booked by the stop watcher. ``SAFETY_CLOSE``:
    the system closed a position by itself, SS.5's confirm job when a stop cannot be shown
    to rest. ``MANUAL``: a trade a person did, either by hand at the venue and booked through
    reconciliation, or a close the user asked for from the panel (SS.9), which the worker sends
    through ``ClosePosition``.
    """

    SIGNAL = "SIGNAL"
    STOP = "STOP"
    SAFETY_CLOSE = "SAFETY_CLOSE"
    MANUAL = "MANUAL"


ALREADY_FLAT = "ALREADY_FLAT"
"""The mark that opens the error of a close the venue refused because its position was
already flat (SS.7): the stop most likely fired while the close was in flight, so the
close is FAILED but nothing went wrong, and a reverse's continuation waits for the stop's
booking instead of abandoning."""


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """One attempt to submit an order, either opening a position or closing
    one.

    ``reservation_id`` / ``closes_allocation_id`` mirror the
    ``ck_execution_attempts_one_origin`` CHECK: exactly one is set, and which
    one says what kind of order this is. An open is bound to the reservation
    whose capital it spends. A close is bound to the allocation whose position
    it is unwinding — it reserves nothing, because a FILLED reservation has
    already stopped counting toward pool availability and the spend is visible
    in the exchange balance instead.

    ``leverage`` (migration ``0015``) is set only for a futures order and
    NULL for a spot one. It is captured when the order is sized rather than
    read back later, because it is a per-symbol account setting the owner can
    change from Pionex's own UI: the multiple in force an hour after the fact
    is not necessarily the one that decided this position's size. NULL means
    "not a futures order" -- defaulting it to 1 would make a spot fill
    indistinguishable from a futures position at 1x, which liquidates.

    ``quantity`` and ``quote_amount`` mirror ``MarketSell``/``MarketBuy``:
    exactly one of them is set, and it is the number that actually went on the
    wire. Recording a base quantity for a buy would put a figure in the
    database that was never sent to anyone — derived from a stale alert price
    and impossible to reconcile against the exchange. What the order really
    filled at belongs to the ledger, which reads it from the fills.
    """

    id: UUID
    reservation_id: UUID | None
    closes_allocation_id: UUID | None
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    side: OrderSide
    quantity: Decimal | None
    quote_amount: Decimal | None
    leverage: Decimal | None
    status: ExecutionStatus
    origin: ExecutionOrigin
    client_order_id: str
    exchange_order_id: str | None = None
    error: str | None = None
    # ``execution_attempts.signal_id`` (migration ``0025``, decision 25): the
    # signal this attempt was placed for. ``None`` for an attempt written
    # before PR 5c, for an orphan close (no signal asked for it) and for a
    # VENUE-origin booking -- and ``None`` records nothing at settle.
    signal_id: UUID | None = None
    # ``execution_attempts.delivery_id`` (migration ``0032``, tasks.md C.7): the
    # delivery whose work placed this attempt, and so the row its outcome lands
    # on. It is written beside ``signal_id``, never instead of it. ``None`` for the
    # same attempts ``signal_id`` is, and nothing is recorded for those at settle.
    delivery_id: UUID | None = None
    # ``execution_attempts.cause`` (migration ``0043``). Every production writer names it:
    # ``PlaceOrder`` SIGNAL, ``ClosePosition`` the command's, the booking writer MANUAL, the
    # stop watcher STOP. The default exists only so the many test fixtures of an ordinary
    # signal attempt stay as they were.
    cause: ExecutionCause = ExecutionCause.SIGNAL
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Mirrors the two CHECK constraints, so an invalid attempt fails at
        construction rather than on the INSERT."""
        if (self.reservation_id is None) == (self.closes_allocation_id is None):
            raise InvariantViolation(
                "an ExecutionAttempt has exactly one origin: reservation_id for "
                "an opening order, or closes_allocation_id for a closing one"
            )
        if (self.quantity is None) == (self.quote_amount is None):
            raise InvariantViolation(
                "an ExecutionAttempt carries exactly one size: quantity for a "
                "sell (base) or quote_amount for a buy (quote)"
            )
        if self.origin is ExecutionOrigin.VENUE and self.status is not ExecutionStatus.FILLED:
            raise InvariantViolation(
                "a VENUE-origin ExecutionAttempt must be constructed already "
                "FILLED -- the fill already happened at the venue, so it never "
                "passes through SUBMITTED and is never sent to ExchangePort"
            )
        if self.origin is ExecutionOrigin.VENUE and self.closes_allocation_id is None:
            raise InvariantViolation(
                "a VENUE-origin ExecutionAttempt must set closes_allocation_id "
                "-- it always unwinds a position ApproveBooking already "
                "matched to an allocation; an OPEN with no allocation to "
                "unwind is NO_MATCHING_ALLOCATION, which is unbookable"
            )

    @property
    def allocation_id(self) -> UUID:
        """The allocation this attempt's fills belong to.

        For an open it is the reservation that funded it; for a close it is the
        allocation being unwound. Both land in the same ``ledger_entries``
        column on purpose — that is what lets a close net against its open when
        positions are projected from the ledger (CLAUDE.md rule 6).
        """
        allocation = self.reservation_id or self.closes_allocation_id
        if allocation is None:  # pragma: no cover - __post_init__ forbids it
            raise InvariantViolation("ExecutionAttempt has no allocation")
        return allocation

    @property
    def is_closing(self) -> bool:
        return self.closes_allocation_id is not None

    @property
    def refused_as_already_flat(self) -> bool:
        """A FAILED close the venue refused because the position was already flat."""
        return (
            self.status is ExecutionStatus.FAILED
            and self.error is not None
            and self.error.startswith(f"{ALREADY_FLAT}:")
        )

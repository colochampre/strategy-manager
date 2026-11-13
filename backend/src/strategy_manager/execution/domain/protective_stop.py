"""The protective stop of an opening (subscriber-safety D1; tasks.md SS.5).

Every live futures opening carries a stop loss that rests at the exchange, so a
position is protected when its user never signs in, its author stops signalling, or
this system is down. This module holds what the system keeps about one: a row per
opening attempt, written with the attempt and before the order is sent, so a crash
leaves a trace of a stop that may exist at the venue.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from strategy_manager.execution.domain.order import OrderSide


class StopStatus(StrEnum):
    """Where a stop stands.

    ``PENDING``: sent with the opening, not yet found resting. ``RESTING``: found, with
    the id the venue gave it. ``FAILED``: not found, so the position is closed at once.
    ``GONE``: the position closed by other means, so there is nothing left to protect.
    ``VOID``: the opening ended without fills, so no stop ever mattered.
    ``SIMULATED``: a simulated opening, which records the level it would have used and
    places no stop. (SS.7 adds ``FIRED``.)"""

    PENDING = "PENDING"
    RESTING = "RESTING"
    FAILED = "FAILED"
    GONE = "GONE"
    VOID = "VOID"
    SIMULATED = "SIMULATED"


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


def position_side_of(opening: OrderSide) -> PositionSide:
    """The side of the position an opening order creates: a BUY opens a LONG, a SELL a
    SHORT."""
    return PositionSide.LONG if opening is OrderSide.BUY else PositionSide.SHORT


@dataclass(frozen=True, slots=True)
class ProtectiveStop:
    """One opening attempt's stop.

    ``allocation_id`` is the reservation that funded the opening, the id its fills carry
    in the ledger. ``stop_loss_pct`` is the level the stop was placed at, carried from
    the policy the leverage cap was checked against. ``trigger_price`` is where it rests,
    ``None`` when no price was worked out (a simulated opening). ``venue_stop_id`` is the
    id the venue gave it, ``None`` until it is found resting."""

    id: UUID
    execution_attempt_id: UUID
    allocation_id: UUID
    exchange: str
    venue: str
    symbol: str
    position_side: PositionSide
    stop_loss_pct: Decimal
    trigger_price: Decimal | None
    status: StopStatus
    venue_stop_id: str | None = None

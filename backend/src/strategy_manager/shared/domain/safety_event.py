"""``NewSafetyEvent``: one thing the system did to protect a user's money, or refused to
do, that the user must be able to read about (subscriber-safety SS.10, spec safety-events).

An event is written in the SAME transaction as the change it reports, so it exists exactly
when its cause does, and is never updated or deleted. Its source is the row that caused it,
which is what keeps a re-run from writing it twice:

* ``execution_attempt_id`` for the four events a booked order causes (a stop that fired,
  and the three closes);
* ``delivery_id`` for an opening that was refused, which has no order and no allocation.

Exactly one of the two is set. ``detail`` holds strings only: a ``Decimal`` is written as
the text a person reads, never a float.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation


class SafetyEventKind(StrEnum):
    """Mirrors ``ck_safety_events_kind`` (migration ``0044``)."""

    STOP_FIRED = "STOP_FIRED"
    STOP_FAILED_CLOSED = "STOP_FAILED_CLOSED"
    STRATEGY_STOPPED_CLOSED = "STRATEGY_STOPPED_CLOSED"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    OPENING_REFUSED_LEVERAGE_CAP = "OPENING_REFUSED_LEVERAGE_CAP"
    OPENING_REFUSED_ACCOUNT_SUSPENDED = "OPENING_REFUSED_ACCOUNT_SUSPENDED"
    OPENING_REFUSED_AUTHOR_SUSPENDED = "OPENING_REFUSED_AUTHOR_SUSPENDED"


@dataclass(frozen=True, slots=True)
class NewSafetyEvent:
    user_id: UUID
    kind: SafetyEventKind
    strategy_id: UUID
    allocation_id: UUID | None
    exchange: str
    venue: str
    symbol: str
    detail: Mapping[str, str]
    execution_attempt_id: UUID | None = None
    delivery_id: UUID | None = None

    def __post_init__(self) -> None:
        if (self.execution_attempt_id is None) == (self.delivery_id is None):
            raise InvariantViolation(
                "a safety event names exactly one source: the execution attempt that "
                "booked it, or the delivery that was refused"
            )
        if not all(isinstance(value, str) for value in self.detail.values()):
            raise InvariantViolation("a safety event's detail holds strings only")

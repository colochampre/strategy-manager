"""What the notifications feed needs from the rest of the system, as its own ports
(panel-redesign RD.5a). Each port answers ONE source in the shape this module
reads; the adapters (``infrastructure/``) fill them from the other modules' own
reads, and none of them calls an exchange.

Every port but the discrepancies' is the signed-in user's own rows (multi-user
design AD8). The discrepancies' is the whole system's, and the use case asks it
for an admin only.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ClosedFacts:
    """How an operation ended. ``close_cause`` is the trades read's own
    (``SIGNAL``, ``MANUAL_CLOSE``, ``STOP_FIRED``, ...)."""

    closed_at: datetime
    exit_price: Decimal | None
    pnl: Decimal
    close_cause: str


@dataclass(frozen=True, slots=True)
class OperationFacts:
    """One operation of the user, open or closed, live or rehearsal.
    ``opened_at`` is ``None`` when its opening instant is unknown. ``leverage`` is
    what the opening attempt recorded; ``None`` for spot or when absent."""

    allocation_id: UUID
    strategy_id: UUID | None
    strategy_name: str | None
    exchange: str
    venue: str
    currency: str
    pair: str | None
    side: str | None
    rehearsal: bool
    opened_at: datetime | None
    entry_price: Decimal | None
    leverage: Decimal | None
    closed: ClosedFacts | None


class OperationSourcePort(Protocol):
    async def operations(self, user_id: UUID) -> Sequence[OperationFacts]: ...


@dataclass(frozen=True, slots=True)
class RefusalFacts:
    """One refused opening the safety events recorded. ``kind`` is the event's kind
    (``OPENING_REFUSED_LEVERAGE_CAP``, ...); ``symbol`` is as stored."""

    event_id: UUID
    kind: str
    strategy_id: UUID
    strategy_name: str
    exchange: str
    venue: str
    symbol: str
    occurred_at: datetime
    detail: dict[str, str] = field(default_factory=dict)


class RefusalSourcePort(Protocol):
    async def refusals(self, user_id: UUID) -> Sequence[RefusalFacts]: ...


@dataclass(frozen=True, slots=True)
class NoticeFacts:
    """One rejected delivery. There is no free text on it: the delivery's own
    ``outcome_detail`` carries ids and is never read."""

    delivery_id: UUID
    reason: str
    strategy_id: UUID
    strategy_name: str
    exchange: str
    venue: str
    currency: str
    symbol: str
    decided_at: datetime


class NoticeSourcePort(Protocol):
    async def notices(
        self, user_id: UUID, reasons: Collection[str]
    ) -> Sequence[NoticeFacts]:
        """The user's ``REJECTED`` deliveries whose reason is one of ``reasons``."""
        ...


@dataclass(frozen=True, slots=True)
class DiscrepancyFacts:
    discrepancy_id: UUID
    exchange: str
    venue: str
    currency: str
    symbol: str
    kind: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class DiscrepancyReading:
    """The confirmed discrepancies that need the owner's decision. ``dry_run`` is
    the reading's own: true under the brake and when the scan skips every user,
    and then nothing is being compared for anyone."""

    dry_run: bool
    needs_owner: tuple[DiscrepancyFacts, ...] = ()


class DiscrepancySourcePort(Protocol):
    async def needs_owner(self) -> DiscrepancyReading: ...

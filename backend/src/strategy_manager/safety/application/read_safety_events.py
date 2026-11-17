"""``ReadSafetyEvents``: the safety events one user can read (subscriber-safety SS.10).

A user reads their OWN events and nobody else's, an admin included: the user id is the
reader's argument, never a filter a caller can leave out. Newest first, and at most
``LIMIT``: the list is a recent history, not an export.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.domain.safety_event import SafetyEventKind

LIMIT = 100


@dataclass(frozen=True, slots=True)
class SafetyEventView:
    id: UUID
    kind: SafetyEventKind
    strategy_id: UUID
    strategy_name: str
    allocation_id: UUID | None
    exchange: str
    venue: str
    symbol: str
    occurred_at: datetime
    detail: dict[str, str]


class SafetyEventReaderPort(Protocol):
    async def newest_of(self, user_id: UUID, limit: int) -> list[SafetyEventView]:
        """``user_id``'s events, newest first, at most ``limit``."""
        ...


class ReadSafetyEvents:
    def __init__(self, reader: SafetyEventReaderPort) -> None:
        self._reader = reader

    async def read(self, user_id: UUID) -> list[SafetyEventView]:
        return await self._reader.newest_of(user_id, LIMIT)

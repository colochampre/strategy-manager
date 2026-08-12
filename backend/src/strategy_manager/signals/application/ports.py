"""Ports (Protocols) owned by ``signals``.

Consumer declares the port, provider owns the adapter — the router (the
composition point for this module) is the only place that binds them.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.signals.domain.signal import WebhookSignal


@dataclass(frozen=True, slots=True)
class InsertOutcome:
    """Result of an idempotent insert: which id, and whether it was new."""

    signal_id: UUID
    inserted: bool


class SignalRepositoryPort(Protocol):
    """Idempotent persistence: ``ON CONFLICT (strategy_id, idempotency_key)
    DO NOTHING`` semantics, resolved to the existing row on conflict."""

    async def insert_or_get(self, signal: WebhookSignal) -> InsertOutcome: ...


class WebhookAuthPort(Protocol):
    """Authenticates a webhook request by source IP and shared secret."""

    def authenticate(self, source_ip: str | None, provided_secret: str | None) -> bool: ...


class CommitPort(Protocol):
    """The minimal capability ``IngestSignal`` needs to finalize its
    transaction. Deliberately narrower than ``shared.UnitOfWorkPort`` so any
    object with an async ``commit()`` (including a raw ``AsyncSession``)
    satisfies it structurally, without leaking SQLAlchemy into this layer."""

    async def commit(self) -> None: ...

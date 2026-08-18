"""The WebhookSignal aggregate: a persisted, authenticated TradingView alert.

Carries the typed alert fields (``action``, ``contracts``, ``position_size``,
``price``, ``symbol``, ``signal_type``) as first-class columns, not just an
opaque payload blob — the open/close transition cannot be reconstructed
later without them (design.md § "position_size routes the signal").
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation


class SignalStatus(StrEnum):
    """Mirrors the ``signals.status`` CHECK constraint."""

    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Wraps the derived idempotency key, enforcing the DB CHECK bound."""

    value: str

    def __post_init__(self) -> None:
        if not (1 <= len(self.value) <= 200):
            raise InvariantViolation(
                f"idempotency key length must be between 1 and 200 chars, got {len(self.value)}"
            )


@dataclass(frozen=True, slots=True)
class WebhookSignal:
    """A signal accepted from the webhook, ready to persist idempotently."""

    strategy_id: UUID
    idempotency_key: IdempotencyKey
    action: str
    contracts: Decimal
    position_size: Decimal
    price: Decimal
    symbol: str
    signal_type: str
    raw_payload: dict[str, Any]
    id: UUID | None = None
    received_at: datetime | None = None
    status: SignalStatus = SignalStatus.ACCEPTED
    job_id: UUID | None = None

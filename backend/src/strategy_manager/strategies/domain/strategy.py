"""Strategy aggregate: a registered TradingView strategy with a target
capital pool and a fill policy (design.md § strategies/domain/strategy.py).

No framework imports, per the layering rule that ``domain`` never depends on
FastAPI, SQLAlchemy or httpx.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Venue


class FillMode(StrEnum):
    """Mirrors the ``strategies.fill_mode`` CHECK constraint."""

    SKIP = "SKIP"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class AllocationPolicy:
    """The pool a strategy targets and how it behaves under partial
    availability. Extracted as a VO because these three fields are always
    read and validated together — they are the strategy's whole allocation
    policy (design.md's ``strategies`` table columns)."""

    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode


@dataclass(frozen=True, slots=True)
class Strategy:
    """A registered strategy. ``id`` MUST equal the ``signal_type`` UUID the
    owner already pastes into TradingView (design.md § "strategy_id derives
    from signal_type" — HARD CONSTRAINT ON SLICE 3) — it is never generated
    by this object or by persistence."""

    id: UUID
    name: str
    policy: AllocationPolicy
    enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise InvariantViolation("Strategy.name must be non-empty")

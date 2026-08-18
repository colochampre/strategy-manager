"""``LedgerEntry``: the append-only record of one fill (design.md §
execution/ and ledger/ (slice 5); spec: trade-ledger § Ledger Row Content,
§ Native Settlement-Currency Reporting).

Frozen and deliberately carries zero mutator methods: the ledger is
append-only end to end, including at the domain layer, not only at the
database (CLAUDE.md rule 6).
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Mirrors a row of ``ledger_entries`` (migration ``0005``). Every
    monetary field is recorded in this row's own pool's native settlement
    currency — never blended into a cross-pool USD total (CLAUDE.md rule 7)."""

    id: UUID
    strategy_id: UUID
    allocation_id: UUID
    execution_attempt_id: UUID
    venue: str
    settlement_currency: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    fee_currency: str
    notional: Decimal
    exchange_order_id: str
    exchange_fill_id: str
    filled_at: datetime
    usd_rate_at_fill: Decimal
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise InvariantViolation("LedgerEntry.quantity must be positive")
        if self.price <= 0:
            raise InvariantViolation("LedgerEntry.price must be positive")
        if self.fee < 0:
            raise InvariantViolation("LedgerEntry.fee must not be negative")
        if self.usd_rate_at_fill <= 0:
            raise InvariantViolation("LedgerEntry.usd_rate_at_fill must be positive")

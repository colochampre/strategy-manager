"""``LockKey`` VO: the ordered text pair handed to Postgres' ``hashtext()``
inside ``pg_advisory_xact_lock`` (design.md's ``PgAdvisoryLockAdapter`` and
§ Interfaces / Contracts — ``AdvisoryLockPort.acquire(key: LockKey)``).
"""

from dataclasses import dataclass

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.shared.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class LockKey:
    """Plain text, not the domain enums: this is exactly what gets bound into
    the raw SQL ``hashtext(:venue), hashtext(:settlement_currency)`` call."""

    venue: str
    settlement_currency: str

    def __post_init__(self) -> None:
        if not self.venue or not self.settlement_currency:
            raise InvariantViolation(
                "LockKey requires a non-empty venue and settlement_currency"
            )

    @classmethod
    def from_pool_key(cls, pool_key: PoolKey) -> "LockKey":
        return cls(
            venue=pool_key.venue.value, settlement_currency=pool_key.settlement_currency.value
        )

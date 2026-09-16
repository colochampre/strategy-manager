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
    the raw SQL ``hashtext(:first), hashtext(:second)`` call.

    ``pg_advisory_xact_lock`` takes two 32-bit keys and a pool is now
    identified by three values, so the exchange and the venue share the first
    one as ``exchange:venue``. Putting the exchange into the pair rather than
    alongside it is what stops Bybit's ``usdt-m/USDT`` and Binance's from
    serializing against each other -- two unrelated pools waiting on one lock,
    which is the collision the startup invariant exists to catch.
    """

    exchange: str
    venue: str
    settlement_currency: str

    def __post_init__(self) -> None:
        if not self.exchange or not self.venue or not self.settlement_currency:
            raise InvariantViolation(
                "LockKey requires a non-empty exchange, venue and settlement_currency"
            )

    @property
    def first(self) -> str:
        """The first ``hashtext`` input: the exchange and venue together."""
        return f"{self.exchange}:{self.venue}"

    @property
    def second(self) -> str:
        """The second ``hashtext`` input."""
        return self.settlement_currency

    @classmethod
    def from_pool_key(cls, pool_key: PoolKey) -> "LockKey":
        return cls(
            exchange=pool_key.exchange.value,
            venue=pool_key.venue.value,
            settlement_currency=pool_key.settlement_currency.value,
        )

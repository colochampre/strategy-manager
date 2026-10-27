"""``LockKey`` VO: the ordered text pair handed to Postgres' ``hashtext()``
inside ``pg_advisory_xact_lock`` (design.md's ``PgAdvisoryLockAdapter`` and
§ Interfaces / Contracts — ``AdvisoryLockPort.acquire(key: LockKey)``).
"""

from dataclasses import dataclass
from uuid import UUID

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

    The pool's owner is folded in as well (multi-user design AD2, B.4): a pool
    is one user's pool on a market, never the market alone. ``LockKey`` decides
    how the four values fold into the two hash inputs, so no call site does.
    The id is used rather than the pool's own id because callers hold the
    market and the user, not the pool row, and because single-bigint advisory
    locks elsewhere (``recurring_jobs``) could collide with small pool ids.
    """

    exchange: str
    venue: str
    settlement_currency: str
    user_id: UUID

    def __post_init__(self) -> None:
        if not self.exchange or not self.venue or not self.settlement_currency:
            raise InvariantViolation(
                "LockKey requires a non-empty exchange, venue and settlement_currency"
            )
        if self.user_id.int == 0:
            raise InvariantViolation("LockKey requires a non-empty user_id")

    @property
    def first(self) -> str:
        """The first ``hashtext`` input: the exchange and venue together."""
        return f"{self.exchange}:{self.venue}"

    @property
    def second(self) -> str:
        """The second ``hashtext`` input: the settlement currency and the pool's
        owner. Two users on one market hold different money, so the user is part
        of the lock's identity; it rides in the second input so ``first`` keeps
        the exchange and venue together."""
        return f"{self.settlement_currency}:{self.user_id}"

    @classmethod
    def from_pool_key(cls, user_id: UUID, pool_key: PoolKey) -> "LockKey":
        return cls(
            user_id=user_id,
            exchange=pool_key.exchange.value,
            venue=pool_key.venue.value,
            settlement_currency=pool_key.settlement_currency.value,
        )

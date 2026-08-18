"""``CapitalPool`` aggregate: a pool's balance state at decision time
(design.md § The AllocationDecision Algorithm — ``decide(pool, ...)``).
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.allocation.domain.pool_key import PoolKey


@dataclass(frozen=True, slots=True)
class CapitalPool:
    """``balance`` is the live pool balance; ``reserved_active`` is the sum of
    that pool's non-expired ``PENDING``/``SUBMITTED`` reservations (spec:
    capital-allocation § Pool Availability)."""

    key: PoolKey
    balance: Decimal
    reserved_active: Decimal

    @property
    def available(self) -> Decimal:
        """Clamped at 0: a balance that dropped below its reservations must
        never yield a negative grant (design.md's "Negative availability"
        edge case)."""

        return max(self.balance - self.reserved_active, Decimal("0"))

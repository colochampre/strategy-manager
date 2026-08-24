"""``AllocationRules`` VO (design.md's component inventory § allocation/domain
/rules.py).

``FillMode`` is redefined locally rather than imported from
``strategies.domain.strategy``: no ``domain`` module ever imports another
module's ``domain`` (design.md's cross-module wiring rule). The decoupling
mirrors ``StrategyPolicySnapshot.fill_mode``, which already carries this value
as a plain string across the module boundary for exactly this reason.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from strategy_manager.shared.domain.errors import InvariantViolation


class FillMode(StrEnum):
    """Mirrors the ``strategies.fill_mode`` CHECK constraint values."""

    SKIP = "SKIP"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class AllocationRules:
    """``min_order_size`` lives on the pool, never on the strategy (design.md's
    "Decision: min order size lives on the pool").

    It is the smallest position that can still be CLOSED, not the smallest the
    venue will accept as one order -- see ``PoolConfig``. Granting less than
    this is how capital gets locked in a position that cannot be exited, which
    is why rules 1 and 5 skip rather than shrink below it.
    """

    fill_mode: FillMode
    min_order_size: Decimal

    def __post_init__(self) -> None:
        if self.min_order_size <= 0:
            raise InvariantViolation("AllocationRules.min_order_size must be positive")

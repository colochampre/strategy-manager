"""``StopLossPct``: where a strategy's positions are stopped, as a percentage of
price from the entry (subscriber-safety D5).

Every seat exits at the same price as the strategy, and the level caps the leverage
a seat may choose (``shared.domain.leverage.max_leverage``), so the stop comes before
liquidation. Mirrors the ``ck_strategies_stop_loss_pct_range`` CHECK of migration
``0040``: 1 to 50 inclusive, at most two decimals.
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.shared.domain.errors import InvariantViolation

MIN_STOP_LOSS_PCT = Decimal("1")
MAX_STOP_LOSS_PCT = Decimal("50")
STOP_LOSS_DECIMALS = 2


@dataclass(frozen=True, slots=True)
class StopLossPct:
    value: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise InvariantViolation("StopLossPct.value must be a Decimal")
        if not self.value.is_finite() or not (
            MIN_STOP_LOSS_PCT <= self.value <= MAX_STOP_LOSS_PCT
        ):
            raise InvariantViolation(
                f"a stop level goes from {MIN_STOP_LOSS_PCT} to {MAX_STOP_LOSS_PCT} percent"
            )
        exponent = self.value.as_tuple().exponent
        # Counted on the value as written (``7.50`` is two places), never normalized.
        if isinstance(exponent, int) and exponent < -STOP_LOSS_DECIMALS:
            raise InvariantViolation("a stop level has at most two decimals")


#: Offered at registration and given to every strategy that existed at deploy (D6).
DEFAULT_STOP_LOSS_PCT = StopLossPct(Decimal("10"))

"""PoolConfig VO: a configured capital pool's static configuration
(design.md § accounts/domain/pool_config.py). ``min_order_size`` lives here,
never on ``strategies`` (design.md's "Choice" note on the shared boundary).
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Venue


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Mirrors a row of ``capital_pools`` — the single source of truth for
    which pools exist. There is no parallel ``CONFIGURED_POOLS`` env list."""

    venue: Venue
    settlement_currency: Currency
    min_order_size: Decimal
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.min_order_size <= 0:
            raise InvariantViolation("PoolConfig.min_order_size must be positive")

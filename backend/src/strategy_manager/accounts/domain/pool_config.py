"""PoolConfig VO: a configured capital pool's static configuration
(design.md § accounts/domain/pool_config.py). ``min_order_size`` lives here,
never on ``strategies`` (design.md's "Choice" note on the shared boundary).

``min_order_size`` is NOT the venue's minimum for one order. It is the
smallest position that survives a ROUND TRIP, which is a larger number, and
the difference is not academic: a position opened at the venue's own minimum
cannot be closed. Fees and base-precision rounding shrink it between open and
close, and the venue applies the same minimum to the closing order's notional.

That was verified live on Pionex (migration ``0014``): buying exactly 10 USDT
of ETH, the venue's ``minAmount``, produced a holding worth 9.98 that the
venue then refused to sell. In production that capital would be locked in a
position the system could never exit, because every close attempt would be
rejected identically.
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Exchange, Venue


@dataclass(frozen=True, slots=True)
class PoolConfig:
    """Mirrors a row of ``capital_pools`` — the single source of truth for
    which pools exist. There is no parallel ``CONFIGURED_POOLS`` env list.

    ``exchange`` has no default on purpose. Every pool holds real money on one
    named exchange, and a default would let a pool be created without anyone
    deciding where its money is — the one fact that selects both the wallet it
    is sized from and the key its orders are signed with.
    """

    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
    min_order_size: Decimal
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.min_order_size <= 0:
            raise InvariantViolation("PoolConfig.min_order_size must be positive")

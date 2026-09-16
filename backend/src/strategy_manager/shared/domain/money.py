"""Money value object shared across every module.

No framework imports: only ``dataclasses``, ``decimal`` and ``enum``, per the
layering rule that ``domain`` never depends on FastAPI, SQLAlchemy or httpx.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from strategy_manager.shared.domain.errors import InvariantViolation


class Currency(StrEnum):
    """Settlement currencies used by the configured capital pools."""

    USDT = "USDT"
    BTC = "BTC"
    ETH = "ETH"


class Venue(StrEnum):
    """Exchange venues, matching the ``capital_pools.venue`` CHECK constraint."""

    SPOT = "spot"
    USDT_M = "usdt-m"
    COIN_M = "coin-m"


class Exchange(StrEnum):
    """Which exchange a pool's money actually sits on, matching the
    ``capital_pools.exchange`` CHECK constraint.

    Separate from ``Venue`` because they answer different questions. A venue
    says which WALLET and which product — spot, USDⓈ-M, COIN-M — and two
    exchanges both have a ``usdt-m`` one. Without this, a Binance USDT futures
    pool and a Bybit USDT futures pool are the same pool: one row, one lock,
    one balance snapshot, and a ledger that cannot say where a fill happened.

    The value doubles as ``exchange_credentials.exchange``, which is how a
    pool's rows reach the key that signs its orders.
    """

    PIONEX = "pionex"
    BYBIT = "bybit"
    BINANCE = "binance"


@dataclass(frozen=True, slots=True)
class Money:
    """An amount in a specific currency. All arithmetic is exact Decimal."""

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise InvariantViolation("Money.amount must be a Decimal")

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(self.amount - other.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount >= other.amount

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise InvariantViolation(
                f"currency mismatch: {self.currency} != {other.currency}"
            )

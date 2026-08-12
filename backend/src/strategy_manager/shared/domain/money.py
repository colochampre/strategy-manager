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

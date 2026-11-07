"""``Leverage``: the leverage a user chose for one subscription (decision 38).

Each user chooses their own, from 1 to ``MAX_LEVERAGE``, and every live opening
of that subscription is placed at it. The cap is the owner's ("Pongamos x20
tope"), not a venue's: a venue's maximum varies per pair, and Binance gates
anything above 20x behind account checks. Mirrors the
``ck_subscriptions_leverage_range`` CHECK constraint of migration ``0037``.

It is a whole number. A ``bool`` is refused even though Python counts it as an
``int``: ``True`` is not a leverage anyone chose.
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.shared.domain.errors import InvariantViolation

MAX_LEVERAGE = 20


@dataclass(frozen=True, slots=True)
class Leverage:
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise InvariantViolation("a leverage is an integer")
        if not 1 <= self.value <= MAX_LEVERAGE:
            raise InvariantViolation(f"a leverage goes from 1 to {MAX_LEVERAGE}")

    def notional(self, margin: Decimal) -> Decimal:
        """What a position opened with ``margin`` at this leverage moves: the
        granted amount is margin (CLAUDE.md, "Futures execution")."""
        return margin * self.value


#: Every new seat starts here, the author's at registration included: a
#: subscriber who never looks at the control is placed at one times.
NEW_SEAT_LEVERAGE = Leverage(1)

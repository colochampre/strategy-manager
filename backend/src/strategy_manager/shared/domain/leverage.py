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
from typing import ClassVar

from strategy_manager.shared.domain.errors import DomainError, InvariantViolation

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


def max_leverage(stop_loss_pct: Decimal) -> int:
    """The most a seat may trade a strategy at, given its stop level.

    Under isolated margin a position is liquidated after a price move of about
    ``1 / leverage`` minus the maintenance margin, and a stop beyond the
    liquidation price never fires. So the cap is ``floor(100 / (stop + 1))``: the
    extra point is a buffer for the maintenance margin. It never passes
    ``MAX_LEVERAGE``. 10 gives 9x, and 5 gives 16x."""
    return min(MAX_LEVERAGE, int(Decimal(100) // (stop_loss_pct + 1)))


class LeverageAboveStopCap(DomainError):
    """A leverage above what the strategy's stop level allows (``max_leverage``).
    Carries the maximum so every refusal names it."""

    reason_code: ClassVar[str] = "LEVERAGE_ABOVE_STOP_CAP"

    def __init__(self, leverage: Leverage, stop_loss_pct: Decimal) -> None:
        self.maximum = max_leverage(stop_loss_pct)
        super().__init__(
            f"leverage x{leverage.value} is above the maximum of x{self.maximum} that a "
            f"stop of {format(stop_loss_pct, 'f')}% allows"
        )


def refuse_above_stop_cap(leverage: Leverage, stop_loss_pct: Decimal) -> None:
    """Raises ``LeverageAboveStopCap`` when ``leverage`` is above the cap of
    ``stop_loss_pct``; the one check every path that takes a leverage shares."""
    if leverage.value > max_leverage(stop_loss_pct):
        raise LeverageAboveStopCap(leverage, stop_loss_pct)

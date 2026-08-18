"""``OrderRequest`` VO and the order-quantity derivation (design.md §
execution/ and ledger/ (slice 5); "Alert Contract and Signal Routing" §
"Order size never comes from the alert").

``compute_order_quantity`` takes only ``granted`` (the reservation's already
decided capital amount) and ``price`` (the alert's bar-close reference
price) — there is no ``contracts`` parameter, so the alert's simulated-equity
sizing structurally cannot leak into a live order quantity.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from strategy_manager.shared.domain.errors import InvariantViolation


class OrderSide(StrEnum):
    """Mirrors the ``execution_attempts.side`` / ``ledger_entries.side`` CHECK
    constraint."""

    BUY = "BUY"
    SELL = "SELL"


def compute_order_quantity(granted: Decimal, price: Decimal) -> Decimal:
    """``quantity = granted / price``. ``granted`` is never the alert's
    ``contracts`` field — using TradingView's simulated-equity sizing as a
    real order quantity would size a live position from a backtest's
    imaginary account."""

    if price <= 0:
        raise InvariantViolation("price must be positive to derive an order quantity")
    return granted / price


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """What ``ExchangePort.submit`` receives. ``quantity`` MUST already be
    the result of ``compute_order_quantity`` — this VO only validates the
    invariant, it does not compute it, so the derivation stays auditable at
    the call site."""

    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise InvariantViolation("OrderRequest.quantity must be positive")

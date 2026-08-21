"""Market order VOs and the order-sizing derivation (design.md § execution/
and ledger/ (slice 5); "Alert Contract and Signal Routing" § "Order size
never comes from the alert").

An order is a sum type, not one struct with a side flag, because a market
order is denominated differently depending on which way it goes:

- a market BUY is denominated in the QUOTE currency — you spend an amount
- a market SELL is denominated in the BASE currency — you sell a size

That is not a Pionex quirk to be hidden in an adapter. It is how spot market
orders work on essentially every venue, and it has a real consequence here:
the allocation engine reserves capital in the settlement currency, which IS
the quote currency, so a BUY can carry the granted amount through untouched.
No division, no rounding, no dependency on a price that was already stale
when the alert fired.

Modelling it as ``MarketBuy | MarketSell`` makes the wrong combination
unrepresentable. There is no way to construct a buy carrying a base size,
so there is no way for an adapter to send one.

``market_order`` is the only sanctioned way to build either variant from a
reservation, so the "granted passes through on a buy, granted/price on a
sell" rule lives in one auditable place instead of at every call site.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar

from strategy_manager.shared.domain.errors import InvariantViolation


class OrderSide(StrEnum):
    """Mirrors the ``execution_attempts.side`` / ``ledger_entries.side`` CHECK
    constraint."""

    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class MarketBuy:
    """Spend ``quote_amount`` of the quote currency at the market price.

    ``quote_amount`` is the reservation's granted amount verbatim. Deriving a
    base size here and sending that instead would replace a number the
    allocation engine decided with one computed from the alert's bar-close
    price — a worse number, and one the venue will not accept for a buy
    anyway.
    """

    client_order_id: str
    symbol: str
    quote_amount: Decimal

    side: ClassVar[OrderSide] = OrderSide.BUY

    def __post_init__(self) -> None:
        if self.quote_amount <= 0:
            raise InvariantViolation("MarketBuy.quote_amount must be positive")


@dataclass(frozen=True, slots=True)
class MarketSell:
    """Sell ``base_size`` of the base currency at the market price."""

    client_order_id: str
    symbol: str
    base_size: Decimal

    side: ClassVar[OrderSide] = OrderSide.SELL

    def __post_init__(self) -> None:
        if self.base_size <= 0:
            raise InvariantViolation("MarketSell.base_size must be positive")


OrderRequest = MarketBuy | MarketSell
"""What ``ExchangePort.place`` receives."""


def compute_order_quantity(granted: Decimal, price: Decimal) -> Decimal:
    """``quantity = granted / price``, the base size a market SELL needs.

    ``granted`` is never the alert's ``contracts`` field — using TradingView's
    simulated-equity sizing as a real order quantity would size a live
    position from a backtest's imaginary account. There is no ``contracts``
    parameter here, so it structurally cannot leak in.
    """

    if price <= 0:
        raise InvariantViolation("price must be positive to derive an order quantity")
    return granted / price


def market_order(
    *,
    side: OrderSide,
    client_order_id: str,
    symbol: str,
    granted: Decimal,
    price: Decimal,
) -> OrderRequest:
    """Builds the variant this side actually requires.

    ``price`` is validated for both sides even though only a SELL divides by
    it. A trading alert quoting a non-positive price is a malformed payload,
    and refusing to act on a malformed payload does not depend on whether
    this particular arithmetic happens to need the number.
    """

    if price <= 0:
        raise InvariantViolation("price must be positive to derive an order quantity")

    if side is OrderSide.BUY:
        return MarketBuy(
            client_order_id=client_order_id, symbol=symbol, quote_amount=granted
        )
    return MarketSell(
        client_order_id=client_order_id,
        symbol=symbol,
        base_size=compute_order_quantity(granted, price),
    )

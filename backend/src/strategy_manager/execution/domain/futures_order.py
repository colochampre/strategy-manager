"""The futures market order, and the sizing that derives it from granted
capital.

**Why this is a separate type from ``order.OrderRequest``, and why it is NOT
a sum type.**

``order.py`` models a spot market order as ``MarketBuy | MarketSell`` because
the two sides are denominated differently: a buy spends a QUOTE amount, a sell
sells a BASE size. The sum type makes the wrong pairing unrepresentable, and
that is its entire value.

On futures the premise does not hold. Pionex's ``MARKET_QTY`` is denominated
in the BASE currency whichever way it goes, so there is no wrong pairing left
to make unrepresentable. A sum type here would be two identical shapes wearing
different names, and a reader would reasonably conclude the sides differ in
some way they do not. ``side`` is an honest field precisely because the
denomination is not conditional on it.

Which is also why futures orders cannot simply be added as two more variants
of ``OrderRequest``: doing that would break the invariant that gives that
union its meaning.

**Sizing: the granted amount is MARGIN, not notional.**

``AllocateCapital`` reserves capital out of a pool whose availability is read
from the futures wallet balance -- and a futures wallet holds margin. So a
granted 100 USDT is 100 USDT of margin, and at the leverage the venue has
configured for that symbol it supports a position of ``100 * leverage``
notional::

    size = granted * leverage / price

Reading ``granted`` as notional instead (``size = granted / price``) would
deploy one leverage-th of the margin the allocation engine actually set aside.
On an account at 5x that is 20% of the reserved capital doing any work, which
defeats the whole reason this system exists: strategies competing for the
capital that is genuinely available rather than a locked fraction of it.

**Leverage is carried on the order, not looked up later.**

It is an account setting that can be changed from Pionex's own UI, so the
number that sized a position and the number in force an hour later are not
guaranteed to be the same. The one that sized it is the one that explains the
position, so it travels with the order and is recorded on the execution
attempt. A close never re-derives a size from it -- closes are sized from the
ledger (``HeldPositionPort``), same as on spot.
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.shared.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class FuturesMarketOrder:
    """A ``MARKET_QTY`` order on a perpetual market.

    ``reduce_only`` is what makes a close safe. Without it a closing order
    that races the position -- a stop-out at the venue, a partial fill already
    recorded, a duplicate job -- opens a NEW position in the opposite
    direction instead of flattening the old one. With it, the venue refuses to
    do anything except reduce what is already there.

    ``leverage`` is the number this order was sized at, kept so the position
    stays explainable after the account setting moves.
    """

    client_order_id: str
    symbol: str
    side: OrderSide
    base_size: Decimal
    leverage: Decimal
    reduce_only: bool = False

    def __post_init__(self) -> None:
        if self.base_size <= 0:
            raise InvariantViolation("FuturesMarketOrder.base_size must be positive")
        if self.leverage <= 0:
            raise InvariantViolation("FuturesMarketOrder.leverage must be positive")


def futures_position_size(
    *, granted: Decimal, leverage: Decimal, price: Decimal
) -> Decimal:
    """``size = granted * leverage / price``.

    ``granted`` is margin (see this module's docstring). ``price`` is the
    alert's bar-close reference price -- the only price available before the
    order exists -- and it sizes the order, never the ledger row.

    Multiplication happens before division so the leverage factor is never
    applied to an already-rounded quotient.
    """
    if granted <= 0:
        raise InvariantViolation("granted must be positive to size a futures order")
    if leverage <= 0:
        raise InvariantViolation("leverage must be positive to size a futures order")
    if price <= 0:
        raise InvariantViolation("price must be positive to size a futures order")

    return granted * leverage / price


def open_futures_order(
    *,
    side: OrderSide,
    client_order_id: str,
    symbol: str,
    granted: Decimal,
    leverage: Decimal,
    price: Decimal,
) -> FuturesMarketOrder:
    """Builds the order that OPENS a position from reserved margin.

    The only sanctioned way to turn granted capital into a futures size, so
    the margin-times-leverage rule lives in one auditable place rather than at
    every call site -- the same discipline ``order.market_order`` enforces for
    spot.

    ``reduce_only`` is false and not a parameter: an order built from granted
    capital is by definition opening exposure. Closes are built by
    ``close_futures_order``, which is sized from the ledger instead.
    """
    return FuturesMarketOrder(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        base_size=futures_position_size(
            granted=granted, leverage=leverage, price=price
        ),
        leverage=leverage,
        reduce_only=False,
    )


def close_futures_order(
    *,
    side: OrderSide,
    client_order_id: str,
    symbol: str,
    base_size: Decimal,
    leverage: Decimal,
) -> FuturesMarketOrder:
    """Builds the order that FLATTENS a position the ledger already knows.

    ``base_size`` comes from ``HeldPositionPort``, never from granted capital
    and a price: the fill price differed from the alert's, a market order can
    fill in pieces, and fees move the holding. Only the ledger recorded what
    actually arrived.

    Always ``reduce_only``. A close that cannot reduce should fail at the
    venue rather than open a fresh position in the opposite direction.
    """
    return FuturesMarketOrder(
        client_order_id=client_order_id,
        symbol=symbol,
        side=side,
        base_size=base_size,
        leverage=leverage,
        reduce_only=True,
    )

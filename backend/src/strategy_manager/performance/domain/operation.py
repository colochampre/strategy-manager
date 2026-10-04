"""What one operation (one allocation) shows beyond its PnL: the prices it
entered and left at, its size, its fees and whether its two sides overlap
(design.md, "Addendum: a strategy's operations, listed and opened one by
one", sections B and G).

Pure ``Decimal`` over the ``FillGroup`` aggregates of ONE allocation. The only
imports are the standard library, ``market_symbol`` and ``closed_trade``: no
framework and no I/O. Nothing here converts a currency (CLAUDE.md rule 7).

**Opening and closing side.** The direction (how ``derive_trade`` decided the
operation was opened) names the opening side: a LONG opens on its BUY side, a
SHORT on its SELL side. The other side is the closing side. One rule decides
direction, entry and exit together.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

from strategy_manager.execution.domain.market_symbol import base_currency_of, market_key
from strategy_manager.performance.domain.closed_trade import Direction, FillGroup

BUY = "BUY"
SELL = "SELL"
_ZERO = Decimal(0)

# A quotient is taken in a wider context than the default 28 digits, so that
# rounding to the wire's 18 places happens once, at the edge, and never twice.
QUOTIENT_DIGITS = 60


@dataclass(frozen=True, slots=True)
class FeeAmount:
    """One fee total in the currency it was charged in. Never converted."""

    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class OperationFees:
    """``fees`` is in the pool's settlement currency and is exactly what
    ``derive_trade`` subtracts from the PnL. ``other_fees`` lists every other
    currency whose sum is above zero, each in its own currency."""

    fees: Decimal
    other_fees: tuple[FeeAmount, ...]


@dataclass(frozen=True, slots=True)
class OperationFigures:
    """The four figures that are derived together or not at all."""

    base_currency: str
    entry_price: Decimal
    exit_price: Decimal
    size: Decimal


def operation_fees(groups: Sequence[FillGroup]) -> OperationFees:
    """The fees of ONE allocation: plain sums, nothing converted.

    ``fees`` is every fee charged in the pool's settlement currency, on both
    sides: exactly the amount ``derive_trade`` subtracts from the PnL.
    ``other_fees`` is one entry per other fee currency whose sum is above zero,
    sorted by currency. Currencies are compared and reported upper-cased, as
    ``derive_trade`` compares them.

    It does not decide ``fees_complete``: a fee in the base currency is listed
    here and leaves the flag true (it is already inside the PnL), a fee in a
    third currency is listed and makes the flag false, both as ``derive_trade``
    already decides.
    """
    settlement = groups[0].settlement_currency.upper()
    settlement_fees = _ZERO
    other: dict[str, Decimal] = {}
    for group in groups:
        currency = group.fee_currency.upper()
        if currency == settlement:
            settlement_fees += group.fee
        else:
            other[currency] = other.get(currency, _ZERO) + group.fee
    return OperationFees(
        fees=settlement_fees,
        other_fees=tuple(
            FeeAmount(currency=currency, amount=amount)
            for currency, amount in sorted(other.items())
            if amount > _ZERO
        ),
    )


def _opening_side(direction: Direction) -> str:
    return BUY if direction is Direction.LONG else SELL


def operation_figures(groups: Sequence[FillGroup], direction: Direction) -> OperationFigures | None:
    """Entry price, exit price, size and base currency of ONE allocation, or
    ``None`` when they cannot be derived.

    The entry price is ``sum(notional) / sum(quantity)`` of the opening side,
    the exit price the same over the closing side, and the size the opening
    quantity. ``notional`` is ``quantity * price`` per fill, so the quotient is
    the quantity-weighted average price, never a mean of group averages.

    ``None`` when the groups name more than one market (two spellings of one
    market are not a disagreement) or when a side's summed quantity or notional
    is not above zero. The divisor is checked BEFORE the division.
    """
    if len({market_key(group.symbol) for group in groups}) > 1:
        return None

    opening_side = _opening_side(direction)
    opening = [group for group in groups if group.side == opening_side]
    closing = [group for group in groups if group.side != opening_side]

    opening_quantity = sum((group.quantity for group in opening), _ZERO)
    opening_notional = sum((group.notional for group in opening), _ZERO)
    closing_quantity = sum((group.quantity for group in closing), _ZERO)
    closing_notional = sum((group.notional for group in closing), _ZERO)
    if min(opening_quantity, opening_notional, closing_quantity, closing_notional) <= _ZERO:
        return None

    first = groups[0]
    with localcontext() as context:
        context.prec = QUOTIENT_DIGITS
        entry_price = opening_notional / opening_quantity
        exit_price = closing_notional / closing_quantity

    return OperationFigures(
        base_currency=base_currency_of(first.symbol, first.settlement_currency).upper(),
        entry_price=entry_price,
        exit_price=exit_price,
        size=opening_quantity,
    )


def sides_overlap(groups: Sequence[FillGroup], direction: Direction) -> bool:
    """Whether the opening side's last fill is NOT strictly earlier than the
    closing side's first fill.

    An allocation is closed whole, after it is open, so the system cannot
    produce an overlap; the check exists so that a ledger that did produce one
    is noticed. A tie counts: ``derive_trade`` breaks it in favour of BUY, so
    which side opened would rest on that tie-break alone.
    """
    opening_side = _opening_side(direction)
    opening = [group for group in groups if group.side == opening_side]
    closing = [group for group in groups if group.side != opening_side]
    if not opening or not closing:
        return False
    opening_last = max(group.last_filled_at for group in opening)
    closing_first = min(group.first_filled_at for group in closing)
    return not opening_last < closing_first

"""``derive_trade``: folding the ledger's aggregates of one allocation into a
``ClosedTrade``, or saying it is not one (design.md section 11; spec:
performance-reporting section Realized PnL).

**When is an allocation closed?** When its net base quantity is EXACTLY zero
under the base-fee rule, with both a buy and a sell behind it. There is no
tolerance and no venue step: this is the ledger's own definition
(``net_positions_by_symbol`` drops a group only when its net is exactly zero,
and ``ClosePosition`` sizes a close from that same net), so a trade is closed
here precisely when it has vanished from the open positions. A close that
leaves a remainder, however small, is a position still held. A tolerance would
call an unclosed position closed and book a realized PnL for money still at
risk.

Net base = sum of BUY quantity - sum of SELL quantity - sum of fees charged in
the BASE currency: that much of a purchase never arrived (Pionex spot took a
BUY's fee in the base coin; Bybit charges USDT on both sides, so the term is
zero there).

**The fee rules**, keyed on the currency a fee was charged in:

===============================  =========================  ==============
fee currency                     in ``pnl``                 ``fees_complete``
===============================  =========================  ==============
the settlement currency          subtracted                 unchanged
the base currency                NOT subtracted again: it   unchanged
                                 already reduced the base
                                 that was sold, so it is
                                 in the notional difference
any third currency, fee > 0      not converted, omitted     becomes False
any currency, fee == 0           nothing to subtract        unchanged
===============================  =========================  ==============

Nothing is converted: no rate is read, so no USD or cross-currency figure can
leak in (CLAUDE.md rule 7).

Pure ``Decimal``, no framework, no I/O.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from strategy_manager.execution.domain.market_symbol import base_currency_of, market_key
from strategy_manager.performance.domain.closed_trade import ClosedTrade, FillGroup
from strategy_manager.shared.domain.errors import InvariantViolation

BUY = "BUY"
SELL = "SELL"
_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class DerivedTrades:
    """What one pool's aggregates folded into.

    ``open_trade_count`` counts allocations that are not closed: still open,
    partially closed, or closed against an open the source could not see.
    ``unresolved_allocation_ids`` are allocations whose symbol has no base
    currency in the pool's settlement currency, so the closed test cannot be
    applied to them. They are returned, not dropped, so the caller can make
    them visible.
    """

    closed: tuple[ClosedTrade, ...]
    open_trade_count: int
    unresolved_allocation_ids: tuple[UUID, ...]


def derive_trade(groups: Sequence[FillGroup]) -> ClosedTrade | None:
    """Folds ONE allocation's groups into a trade, or ``None`` if it is not
    closed.

    Raises ``InvariantViolation`` when the symbol cannot be split against the
    pool's settlement currency; ``derive_trades`` turns that into a reported
    id rather than an error for the whole pool.
    """
    first = groups[0]
    settlement = first.settlement_currency.upper()
    base = base_currency_of(first.symbol, first.settlement_currency).upper()

    net_base = _ZERO
    bought = sold = _ZERO
    settlement_fees = _ZERO
    fees_complete = True
    has_buy = has_sell = False

    for group in groups:
        fee_currency = group.fee_currency.upper()
        if group.side == BUY:
            has_buy = True
            bought += group.notional
            net_base += group.quantity
        else:
            has_sell = True
            sold += group.notional
            net_base -= group.quantity

        if fee_currency == base:
            net_base -= group.fee
        elif fee_currency == settlement:
            settlement_fees += group.fee
        elif group.fee > _ZERO:
            fees_complete = False

    if net_base != _ZERO or not (has_buy and has_sell):
        return None

    return ClosedTrade(
        allocation_id=first.allocation_id,
        strategy_id=first.strategy_id,
        exchange=first.exchange,
        venue=first.venue,
        settlement_currency=first.settlement_currency,
        pair=market_key(first.symbol),
        opened_at=min(g.first_filled_at for g in groups),
        closed_at=max(g.last_filled_at for g in groups),
        pnl=sold - bought - settlement_fees,
        fees_complete=fees_complete,
        pool_total_at_open=first.pool_total_at_open,
    )


def derive_trades(groups: Sequence[FillGroup]) -> DerivedTrades:
    """Groups the aggregates per allocation, then derives each. Grouping is
    by ``allocation_id`` and never by symbol: an allocation opened as
    ``SOLUSDT.P`` and closed as ``SOLUSDT`` is one trade (F4)."""
    by_allocation: dict[UUID, list[FillGroup]] = defaultdict(list)
    for group in groups:
        by_allocation[group.allocation_id].append(group)

    closed: list[ClosedTrade] = []
    open_count = 0
    unresolved: list[UUID] = []

    for allocation_id, allocation_groups in by_allocation.items():
        try:
            trade = derive_trade(allocation_groups)
        except InvariantViolation:
            unresolved.append(allocation_id)
            continue
        if trade is None:
            open_count += 1
        else:
            closed.append(trade)

    return DerivedTrades(
        closed=tuple(closed),
        open_trade_count=open_count,
        unresolved_allocation_ids=tuple(unresolved),
    )

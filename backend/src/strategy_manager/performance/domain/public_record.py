"""A strategy's public record: what its author's real trades returned, for anyone
to read (tasks.md G.8, decisions 28, 31 and 34).

It is read from the author's fills, folded per allocation by ``derive_trades``,
never from the signals: an alert's price is not a price anybody traded at, so it
cannot build a record (decision 34). Only the author's fills, in keeping with
decision 22, so a subscriber's capital cannot give a strategy a record.

**Rehearsal fills never count.** The simulated exchange writes them, so a
strategy run on simulated money has no record, however it did. The source
leaves them out and this refuses them again, so a source that forgets cannot
put one on a public page.

**A trade's return is the price move, as if the whole capital were on it.** The
notional of the fills says it: a long returns ``sold / bought - 1`` and a short
``1 - bought / sold``. That is unleveraged, because leverage changes how much is
bought, never the ratio, and before fees, because no fee enters a notional.
Whoever shows it says both.

A trade still open counts for nothing. An allocation whose symbol cannot be
split against its settlement currency has no closed test, so it is returned
among ``unresolved_allocation_ids`` rather than dropped without a word.

**Adding up is the panel's** (``curve.py``): trades of one UTC day are summed
and days are compounded.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.performance.domain.closed_trade import ClosedTrade, Direction, FillGroup
from strategy_manager.performance.domain.curve import compound, sum_by_day
from strategy_manager.performance.domain.derive_trade import (
    BUY,
    SELL,
    DerivedTrades,
    derive_trades,
)

_ZERO = Decimal(0)
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class RecordTrade:
    """A closed trade of the record. ``value`` is its return as a fraction."""

    closed_at: datetime
    value: Decimal


@dataclass(frozen=True, slots=True)
class PublicRecord:
    closed_trade_count: int
    total_return: Decimal
    unresolved_allocation_ids: tuple[UUID, ...]


def _notional(groups: Iterable[FillGroup], side: str) -> Decimal:
    return sum((group.notional for group in groups if group.side == side), _ZERO)


def _return(trade: ClosedTrade, groups: Sequence[FillGroup]) -> Decimal:
    bought, sold = _notional(groups, BUY), _notional(groups, SELL)
    if trade.direction is Direction.LONG:
        return sold / bought - _ONE
    return _ONE - bought / sold


def _derived(groups: Iterable[FillGroup]) -> tuple[tuple[RecordTrade, ...], DerivedTrades]:
    real = [group for group in groups if not group.rehearsal]
    by_allocation: dict[UUID, list[FillGroup]] = defaultdict(list)
    for group in real:
        by_allocation[group.allocation_id].append(group)
    derived = derive_trades(real)
    trades = [
        RecordTrade(trade.closed_at, _return(trade, by_allocation[trade.allocation_id]))
        for trade in derived.closed
    ]
    return tuple(sorted(trades, key=lambda trade: trade.closed_at)), derived


def closed_trades(groups: Iterable[FillGroup]) -> tuple[RecordTrade, ...]:
    """Every closed real trade among one author's fills of one strategy, oldest
    close first."""
    trades, _ = _derived(groups)
    return trades


def build_public_record(groups: Iterable[FillGroup]) -> PublicRecord:
    """The closed trades of one strategy and their compounded return, zero when
    none has closed."""
    trades, derived = _derived(groups)
    points = compound(sum_by_day((trade.closed_at, trade.value) for trade in trades))
    return PublicRecord(
        closed_trade_count=len(trades),
        total_return=points[-1].index - _ONE if points else _ZERO,
        unresolved_allocation_ids=derived.unresolved_allocation_ids,
    )

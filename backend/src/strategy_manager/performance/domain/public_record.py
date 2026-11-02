"""A strategy's public record: what its signals returned, for anyone to read
(tasks.md F.3, decisions 15 and 28).

The figure is the strategy's, not anyone's account. It is built from the
signals alone, whatever became of them, so no ledger, pool or fill reaches it,
and it reads as if the whole capital were on each trade. It is unleveraged and
before fees, and whoever shows it says so.

**A chain is one exact symbol.** Signals are read per ``symbol`` as stored, by
``received_at``, as ``find_prior`` walks them, so ``STXUSDT.P`` and ``STXUSDT``
are two chains. An opening or a closing is not stored; it is read from
``position_size``:

- from flat, a nonzero size opens at that signal's price, and its sign is the
  side;
- to zero, it closes;
- a sign flip closes and opens at the same price;
- a change that keeps the sign, and zero to zero, leave the entry as it is.
  ``PositionTransition.classify`` raises on those two, because for a trade
  they are a defect. A read over history must get past them instead.

A trade still open counts for nothing. A long returns ``exit / entry - 1`` and
a short ``1 - exit / entry``. ``signals.price`` is positive by CHECK, so an
entry is never zero.

**Adding up is the panel's** (``curve.py``): trades of one UTC day are summed
and days are compounded.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from strategy_manager.performance.domain.curve import compound, sum_by_day

_ZERO = Decimal(0)
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class RecordSignal:
    """What the record reads of one stored signal."""

    symbol: str
    received_at: datetime
    position_size: Decimal
    price: Decimal


@dataclass(frozen=True, slots=True)
class RecordTrade:
    """A closed trade of the record. ``value`` is its return as a fraction."""

    symbol: str
    closed_at: datetime
    value: Decimal


@dataclass(frozen=True, slots=True)
class PublicRecord:
    closed_trade_count: int
    total_return: Decimal


@dataclass(frozen=True, slots=True)
class _Entry:
    long: bool
    price: Decimal


def _trade_return(entry: _Entry, exit_price: Decimal) -> Decimal:
    ratio = exit_price / entry.price
    return ratio - _ONE if entry.long else _ONE - ratio


def _closed_in_chain(signals: Iterable[RecordSignal]) -> list[RecordTrade]:
    trades: list[RecordTrade] = []
    entry: _Entry | None = None
    for signal in sorted(signals, key=lambda each: each.received_at):
        size = signal.position_size
        if entry is not None and (size == _ZERO or (size > _ZERO) != entry.long):
            value = _trade_return(entry, signal.price)
            trades.append(RecordTrade(signal.symbol, signal.received_at, value))
            entry = None
        if entry is None and size != _ZERO:
            entry = _Entry(long=size > _ZERO, price=signal.price)
    return trades


def closed_trades(signals: Iterable[RecordSignal]) -> tuple[RecordTrade, ...]:
    """Every closed trade of one strategy, oldest close first."""
    chains: dict[str, list[RecordSignal]] = {}
    for signal in signals:
        chains.setdefault(signal.symbol, []).append(signal)
    trades = [trade for chain in chains.values() for trade in _closed_in_chain(chain)]
    return tuple(sorted(trades, key=lambda trade: trade.closed_at))


def build_public_record(signals: Iterable[RecordSignal]) -> PublicRecord:
    """The closed trades of one strategy and their compounded return, zero
    when none has closed."""
    trades = closed_trades(signals)
    points = compound(sum_by_day((trade.closed_at, trade.value) for trade in trades))
    return PublicRecord(
        closed_trade_count=len(trades),
        total_return=points[-1].index - _ONE if points else _ZERO,
    )

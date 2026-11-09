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

**Adding up is the panel's** (``curve.py``, ``combine_by_day``): within a UTC
day, trades that overlap are summed and trades that follow each other compound;
days are compounded (decision 40).
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.performance.domain.closed_trade import ClosedTrade, Direction, FillGroup
from strategy_manager.performance.domain.curve import (
    CurvePoint,
    IndexPoint,
    MonthReturn,
    RangeName,
    combine_by_day,
    compound,
    drawdowns,
    monthly_grid,
    range_window,
)
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

    opened_at: datetime
    closed_at: datetime
    value: Decimal
    pair: str


@dataclass(frozen=True, slots=True)
class RecordRange:
    """The record over one window ending now: no money, only the return."""

    range: RangeName
    value: Decimal
    trade_count: int


@dataclass(frozen=True, slots=True)
class RecordPair:
    """One market's share of the record. A win is a trade whose return is above zero."""

    pair: str
    trade_count: int
    win_count: int
    win_rate: Decimal
    value: Decimal


@dataclass(frozen=True, slots=True)
class RecordReport:
    """Everything the public page draws of a record, with no amount in it."""

    origin: date | None
    curve: tuple[CurvePoint, ...]
    monthly: tuple[MonthReturn, ...]
    ranges: tuple[RecordRange, ...]
    by_pair: tuple[RecordPair, ...]
    closed_trade_count: int
    max_drawdown: Decimal
    unresolved_allocation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PublicRecord:
    """What a listing shows of a record. ``max_drawdown`` is the deepest fall of the
    compounded curve from a previous top, 0 or below; ``win_rate`` is the share of
    closed trades whose return is above zero, None with no closed trade."""

    closed_trade_count: int
    total_return: Decimal
    max_drawdown: Decimal
    win_rate: Decimal | None
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
        RecordTrade(
            trade.opened_at,
            trade.closed_at,
            _return(trade, by_allocation[trade.allocation_id]),
            trade.pair,
        )
        for trade in derived.closed
    ]
    return tuple(sorted(trades, key=lambda trade: trade.closed_at)), derived


def closed_trades(groups: Iterable[FillGroup]) -> tuple[RecordTrade, ...]:
    """Every closed real trade among one author's fills of one strategy, oldest
    close first."""
    trades, _ = _derived(groups)
    return trades


def _utc_day(moment: datetime) -> date:
    return moment.astimezone(UTC).date()


def _compounded(trades: Sequence[RecordTrade]) -> tuple[IndexPoint, ...]:
    return compound(
        combine_by_day((trade.opened_at, trade.closed_at, trade.value) for trade in trades)
    )


def _return_of(trades: Sequence[RecordTrade]) -> Decimal:
    points = _compounded(trades)
    return points[-1].index - _ONE if points else _ZERO


def _ranges(trades: Sequence[RecordTrade], now: datetime) -> tuple[RecordRange, ...]:
    ranges: list[RecordRange] = []
    for name in RangeName:
        bounds = range_window(name, now)
        if bounds is None:
            window = list(trades)
        else:
            start, end = bounds
            window = [t for t in trades if start <= t.closed_at.astimezone(UTC) <= end]
        ranges.append(RecordRange(name, _return_of(window), len(window)))
    return tuple(ranges)


def _pairs(trades: Sequence[RecordTrade]) -> tuple[RecordPair, ...]:
    grouped: dict[str, list[RecordTrade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.pair].append(trade)
    pairs: list[RecordPair] = []
    for pair in sorted(grouped):
        members = grouped[pair]
        wins = sum(1 for trade in members if trade.value > _ZERO)
        pairs.append(
            RecordPair(
                pair=pair,
                trade_count=len(members),
                win_count=wins,
                win_rate=Decimal(wins) / Decimal(len(members)),
                value=_return_of(members),
            )
        )
    return tuple(pairs)


def build_record_report(groups: Iterable[FillGroup], now: datetime) -> RecordReport:
    """What the public page draws of a record, from the same trades and the same
    return as ``build_public_record``, laid out as the private report lays out a
    pool's: curve, months, ranges ending ``now``, pairs. No amount enters it."""
    trades, derived = _derived(groups)
    points = _compounded(trades)
    dds = drawdowns(points)
    return RecordReport(
        origin=min((_utc_day(trade.opened_at) for trade in trades), default=None),
        curve=tuple(
            CurvePoint(p.day, p.daily_return, p.index, dd)
            for p, dd in zip(points, dds, strict=True)
        ),
        monthly=monthly_grid(points),
        ranges=_ranges(trades, now),
        by_pair=_pairs(trades),
        closed_trade_count=len(trades),
        max_drawdown=min(dds, default=_ZERO),
        unresolved_allocation_ids=derived.unresolved_allocation_ids,
    )


def build_public_record(groups: Iterable[FillGroup]) -> PublicRecord:
    """The closed trades of one strategy, their compounded return and deepest
    fall, zero when none has closed, and their win rate, None then. A win is what
    ``_pairs`` counts as one."""
    trades, derived = _derived(groups)
    points = _compounded(trades)
    wins = sum(1 for trade in trades if trade.value > _ZERO)
    return PublicRecord(
        closed_trade_count=len(trades),
        total_return=points[-1].index - _ONE if points else _ZERO,
        max_drawdown=min(drawdowns(points), default=_ZERO),
        win_rate=Decimal(wins) / Decimal(len(trades)) if trades else None,
        unresolved_allocation_ids=derived.unresolved_allocation_ids,
    )

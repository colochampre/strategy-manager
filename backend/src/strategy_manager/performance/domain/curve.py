"""The compounded return curve and everything read off it (design.md section
11, decisions 12, 16 and 17; spec: performance-reporting).

Everything is per ONE pool, in that pool's native settlement currency, in pure
``Decimal`` with no I/O. Nothing here converts, and nothing sums across pools
(CLAUDE.md rule 7): ``build_pool_performance`` refuses a trade from any other
pool instead of blending it in.

**The formula (confirmed by the owner, decision 17).** Each trade returns
``r_i = pnl_i / pool_total_at_open_i``. Returns of trades that close on the
same UTC day are SUMMED into that day's ``R_d``; days are COMPOUNDED,
``E_d = E_(d-1) * (1 + R_d)``, from ``E_0 = 1``. Summing inside a day is what
keeps two trades that were sized against the same capital from compounding on
each other's gain (decision 12: +20 and +10 on 1,000 is 1.03, not 1.0302).

**Days and months are UTC** (decision 16), taken in this file with
``closed_at.astimezone(UTC).date()``. A database session time zone is never
consulted, and a naive datetime is refused because ``astimezone`` would read
it in the host's zone, which is the same dependence in another place.

**What is left out, and reported.** A trade with no ``pool_total_at_open``
(every reservation written before migration 0026, and the pathological
non-positive total) has no return and never reaches the curve, though its PnL
still counts in the amounts. Open trades and rehearsal fills are not trades at
all. A trade whose fee was charged in a third currency stays in the curve and
is counted. ``Exclusions`` carries each count.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.closed_trade import ClosedTrade
from strategy_manager.performance.domain.derive_trade import DerivedTrades
from strategy_manager.shared.domain.errors import InvariantViolation

_ZERO = Decimal(0)
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class DailyReturn:
    """``R_d``: the summed return of every trade that closed on one UTC day."""

    day: date
    value: Decimal


@dataclass(frozen=True, slots=True)
class IndexPoint:
    """``E_d``: the compounded index at the end of one UTC day."""

    day: date
    daily_return: Decimal
    index: Decimal


@dataclass(frozen=True, slots=True)
class CurvePoint:
    """An index point with its drawdown from the previous peak (<= 0)."""

    day: date
    daily_return: Decimal
    index: Decimal
    drawdown: Decimal


@dataclass(frozen=True, slots=True)
class MonthReturn:
    """A UTC month's return: ``E(end of month) / E(end of previous month) - 1``."""

    year: int
    month: int
    value: Decimal


class RangeName(StrEnum):
    D7 = "7D"
    D30 = "30D"
    D90 = "90D"
    Y1 = "1Y"
    ALL = "All"


# The window length of each range; ``None`` is unbounded (all time).
_RANGE_DAYS: dict[RangeName, int | None] = {
    RangeName.D7: 7,
    RangeName.D30: 30,
    RangeName.D90: 90,
    RangeName.Y1: 365,
    RangeName.ALL: None,
}


@dataclass(frozen=True, slots=True)
class RangeSummary:
    """Realized PnL and compounded return over one window ending now.

    ``pnl`` includes trades that have no capital at open (their amount is
    real); ``value`` cannot, since they have no return. ``trade_count`` counts
    both.
    """

    range: RangeName
    pnl: Decimal
    value: Decimal
    trade_count: int


@dataclass(frozen=True, slots=True)
class Exclusions:
    """What the figures leave out, so that nothing is hidden.

    ``open_trade_count``: allocations not (fully) closed. ``rehearsal_fill_count``:
    DRY_RUN fills the source excluded. ``no_capital_at_open``: closed trades
    with no return (in PnL amounts, not in the curve). ``unconverted_fee``:
    closed trades whose third-currency fee was omitted (they ARE in the
    curve). ``unresolved_allocation_count``: allocations whose symbol could not
    be tested.
    """

    open_trade_count: int
    rehearsal_fill_count: int
    no_capital_at_open: int
    unconverted_fee: int
    unresolved_allocation_count: int


@dataclass(frozen=True, slots=True)
class PoolPerformance:
    pool: PoolKey
    curve: tuple[CurvePoint, ...]
    monthly: tuple[MonthReturn, ...]
    ranges: tuple[RangeSummary, ...]
    closed_trade_count: int
    total_pnl: Decimal
    max_drawdown: Decimal
    exclusions: Exclusions


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise InvariantViolation(
            f"{moment.isoformat()} is a naive datetime; a UTC day cannot be "
            "taken from it without guessing the zone it was written in"
        )
    return moment.astimezone(UTC)


def trade_return(trade: ClosedTrade) -> Decimal | None:
    """``r_i = pnl_i / pool_total_at_open_i``, or ``None`` for a trade with no
    capital at open (it has no return, and is never given a zero one)."""
    capital = trade.pool_total_at_open
    if capital is None:
        return None
    if capital <= _ZERO:
        raise InvariantViolation(
            f"allocation {trade.allocation_id} has a non-positive pool capital "
            f"at open ({capital}); the schema forbids it, so a return cannot be "
            "computed from it"
        )
    return trade.pnl / capital


def daily_returns(trades: Sequence[ClosedTrade]) -> tuple[DailyReturn, ...]:
    """``R_d``: trades with a return, summed per UTC day of ``closed_at``,
    oldest day first. Trades without capital at open are skipped here (and
    counted by ``build_pool_performance``)."""
    by_day: dict[date, Decimal] = {}
    for trade in trades:
        value = trade_return(trade)
        if value is None:
            continue
        day = _utc(trade.closed_at).date()
        by_day[day] = by_day.get(day, _ZERO) + value
    return tuple(DailyReturn(day, value) for day, value in sorted(by_day.items()))


def compound(daily: Sequence[DailyReturn]) -> tuple[IndexPoint, ...]:
    """``E_d = E_(d-1) * (1 + R_d)`` from ``E_0 = 1``."""
    index = _ONE
    points: list[IndexPoint] = []
    for entry in daily:
        index = index * (_ONE + entry.value)
        points.append(IndexPoint(entry.day, entry.value, index))
    return tuple(points)


def drawdowns(points: Sequence[IndexPoint]) -> tuple[Decimal, ...]:
    """``DD_d = E_d / max(E_0..E_d) - 1``, never above zero. ``E_0 = 1`` is
    the first peak, so a pool that loses on its very first day is already
    below where it started."""
    peak = _ONE
    result: list[Decimal] = []
    for point in points:
        peak = max(peak, point.index)
        result.append(point.index / peak - _ONE)
    return tuple(result)


def monthly_grid(points: Sequence[IndexPoint]) -> tuple[MonthReturn, ...]:
    """One entry per UTC month that has at least one closed day, oldest first.
    A month with no closing trade is absent rather than a fabricated 0%."""
    month_end: dict[tuple[int, int], Decimal] = {}
    for point in points:
        month_end[(point.day.year, point.day.month)] = point.index

    previous_end = _ONE
    months: list[MonthReturn] = []
    for (year, month), end in sorted(month_end.items()):
        months.append(MonthReturn(year, month, end / previous_end - _ONE))
        previous_end = end
    return tuple(months)


def range_summary(trades: Sequence[ClosedTrade], now: datetime) -> tuple[RangeSummary, ...]:
    """PnL and compounded return over 7D / 30D / 90D / 1Y (365 days) / All,
    ending ``now``.

    Each window is built from the trades inside it and compounded on its own.
    Slicing the all-time curve would give a different figure, because the
    days on the edge of the window contain only the trades in it. A window
    includes its start instant and ``now``.
    """
    now_utc = _utc(now)
    summaries: list[RangeSummary] = []
    for name, days in _RANGE_DAYS.items():
        if days is None:
            window = list(trades)
        else:
            start = now_utc - timedelta(days=days)
            window = [t for t in trades if start <= _utc(t.closed_at) <= now_utc]
        points = compound(daily_returns(window))
        summaries.append(
            RangeSummary(
                range=name,
                pnl=sum((t.pnl for t in window), _ZERO),
                value=points[-1].index - _ONE if points else _ZERO,
                trade_count=len(window),
            )
        )
    return tuple(summaries)


def _in_pool(pool: PoolKey, trade: ClosedTrade) -> bool:
    return (
        trade.exchange == pool.exchange.value
        and trade.venue == pool.venue.value
        and trade.settlement_currency == pool.settlement_currency.value
    )


def build_pool_performance(
    pool: PoolKey, derived: DerivedTrades, rehearsal_fill_count: int, now: datetime
) -> PoolPerformance:
    """Everything one pool's dashboard shows, from its derived trades.

    Raises ``InvariantViolation`` if any trade belongs to a different pool:
    two pools' returns in one curve is a number with no meaning in any
    currency (CLAUDE.md rule 7), and refusing is the only answer that cannot
    be read as a real figure.
    """
    for trade in derived.closed:
        if not _in_pool(pool, trade):
            raise InvariantViolation(
                f"trade {trade.allocation_id} belongs to pool "
                f"({trade.exchange}, {trade.venue}, {trade.settlement_currency}), "
                f"not to ({pool.exchange.value}, {pool.venue.value}, "
                f"{pool.settlement_currency.value}); a curve is never blended "
                "across pools"
            )

    trades = derived.closed
    points = compound(daily_returns(trades))
    dds = drawdowns(points)

    return PoolPerformance(
        pool=pool,
        curve=tuple(
            CurvePoint(p.day, p.daily_return, p.index, dd)
            for p, dd in zip(points, dds, strict=True)
        ),
        monthly=monthly_grid(points),
        ranges=range_summary(trades, now),
        closed_trade_count=len(trades),
        total_pnl=sum((t.pnl for t in trades), _ZERO),
        max_drawdown=min(dds, default=_ZERO),
        exclusions=Exclusions(
            open_trade_count=derived.open_trade_count,
            rehearsal_fill_count=rehearsal_fill_count,
            no_capital_at_open=sum(1 for t in trades if t.pool_total_at_open is None),
            unconverted_fee=sum(1 for t in trades if not t.fees_complete),
            unresolved_allocation_count=len(derived.unresolved_allocation_ids),
        ),
    )

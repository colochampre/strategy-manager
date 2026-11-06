"""Manual check: how far decision 17's same-day sum is from the exact return.

This is NOT a test. It reads production's ledger, which is why it lives here
and not under tests/. It is READ-ONLY: its one transaction is declared read
only, and it calls no exchange.

**What it measures.** Decision 17 sums ``r_i = pnl_i / pool_total_at_open_i``
over the trades that close on one UTC day, and compounds the days. The sum is
exact for trades that overlap in time, because they were sized against the same
capital. A trade opened after another one closed was sized against a capital
that already held the first one's result, and for those the exact day return
compounds: the sum misses ``r1 * r2``. The error is conservative when same-day
results share a sign and optimistic when they do not, and it compounds with the
days (tasks.md, "Possible improvements").

The exact curve here groups a day's trades that overlap (by ``opened_at`` and
``closed_at``), sums inside each group, and compounds the groups in time order.
Both curves are printed for every pool and every strategy in it, from the same
trades the panel reads (``pool_fills`` -> ``derive_trades``).

Prints no DSN, no credential and no e-mail: a user is the first 8 characters
of their id.

Usage:
    cd backend
    uv run python scripts/compare_same_day_returns.py
On the VPS, as the owner, piped over ssh:
    ssh root@... "cd /opt/strategy-manager/app/backend && sudo -u strategy -H \
        env PYTHONPATH=scripts /opt/strategy-manager/.local/bin/uv run python -" \
        < backend/scripts/compare_same_day_returns.py
"""

import asyncio
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.scope import require_live_only
from strategy_manager.performance.domain.closed_trade import ClosedTrade
from strategy_manager.performance.domain.curve import (
    DailyReturn,
    compound,
    daily_returns,
    trade_return,
)
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.performance.infrastructure.allocation_fills_source import (
    SqlAlchemyAllocationFillsSource,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import create_engine_for
from strategy_manager.shared.domain.money import Currency, Exchange, Venue

_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class Comparison:
    """Both curves over one set of trades.

    ``trades`` counts the trades with a return. ``sequential_days`` counts the
    days whose trades form more than one group, the only days where the two
    curves can differ. The ends are compounded indices from 1.
    """

    trades: int
    days: int
    sequential_days: int
    summed_end: Decimal
    exact_end: Decimal
    largest_day_gap: Decimal


def _groups(trades: Sequence[tuple[ClosedTrade, Decimal]]) -> list[list[Decimal]]:
    """A day's returns, grouped by overlap in time, groups in time order.

    Sorted by ``opened_at``; a trade joins the current group when it opened
    before the group's last close, and starts the next group otherwise.
    """
    groups: list[list[Decimal]] = []
    group_end = None
    for trade, value in sorted(trades, key=lambda pair: pair[0].opened_at):
        if group_end is not None and trade.opened_at < group_end:
            groups[-1].append(value)
            group_end = max(group_end, trade.closed_at)
        else:
            groups.append([value])
            group_end = trade.closed_at
    return groups


def _by_day(trades: Sequence[ClosedTrade]) -> dict[date, list[tuple[ClosedTrade, Decimal]]]:
    days: dict[date, list[tuple[ClosedTrade, Decimal]]] = defaultdict(list)
    for trade in trades:
        value = trade_return(trade)
        if value is not None:
            days[trade.closed_at.astimezone(UTC).date()].append((trade, value))
    return days


def exact_daily_returns(trades: Sequence[ClosedTrade]) -> tuple[DailyReturn, ...]:
    """Each UTC day's return with overlapping trades summed and the groups that
    follow each other compounded. Trades with no capital at open are left out,
    as ``daily_returns`` leaves them out."""
    result: list[DailyReturn] = []
    for day, entries in sorted(_by_day(trades).items()):
        index = _ONE
        for group in _groups(entries):
            index = index * (_ONE + sum(group, Decimal(0)))
        result.append(DailyReturn(day, index - _ONE))
    return tuple(result)


def compare(trades: Sequence[ClosedTrade]) -> Comparison:
    summed = daily_returns(trades)
    exact = exact_daily_returns(trades)
    sequential = sum(1 for entries in _by_day(trades).values() if len(_groups(entries)) > 1)
    summed_points = compound(summed)
    exact_points = compound(exact)
    return Comparison(
        trades=sum(len(entries) for entries in _by_day(trades).values()),
        days=len(summed),
        sequential_days=sequential,
        summed_end=summed_points[-1].index if summed_points else _ONE,
        exact_end=exact_points[-1].index if exact_points else _ONE,
        largest_day_gap=max(
            (abs(s.value - e.value) for s, e in zip(summed, exact, strict=True)),
            default=Decimal(0),
        ),
    )


def _percent(value: Decimal) -> str:
    return f"{value * 100:+.2f}%"


def _line(label: str, result: Comparison) -> str:
    gap = result.summed_end - result.exact_end
    relative = gap / result.exact_end if result.exact_end else Decimal(0)
    return (
        f"  {label:<40} trades={result.trades:<4} days={result.days:<4} "
        f"sequential_days={result.sequential_days:<4} "
        f"summed={_percent(result.summed_end - _ONE):>9} "
        f"exact={_percent(result.exact_end - _ONE):>9} "
        f"gap={gap * 100:+.3f}pp of index ({relative * 100:+.3f}% relative) "
        f"largest_day_gap={result.largest_day_gap * 100:.3f}pp"
    )


async def _run(session: AsyncSession) -> None:
    await session.execute(text("SET TRANSACTION READ ONLY"))
    names = {
        row.id: row.name for row in await session.execute(text("SELECT id, name FROM strategies"))
    }
    pools = (
        await session.execute(
            text(
                "SELECT user_id, exchange, venue, settlement_currency FROM capital_pools "
                "ORDER BY user_id, exchange, venue, settlement_currency"
            )
        )
    ).all()
    source = SqlAlchemyAllocationFillsSource(session)
    for user_id, exchange, venue, currency in pools:
        pool = PoolKey(Exchange(exchange), Venue(venue), Currency(currency))
        fills = await source.pool_fills(user_id, pool)
        require_live_only(fills.groups)
        closed = derive_trades(fills.groups).closed
        if not closed:
            continue
        print(f"\nuser {str(user_id)[:8]}  pool {exchange}/{venue}/{currency}")
        print(_line("whole pool", compare(closed)))
        by_strategy: dict[UUID, list[ClosedTrade]] = defaultdict(list)
        for trade in closed:
            by_strategy[trade.strategy_id].append(trade)
        for strategy_id, trades in sorted(by_strategy.items(), key=lambda kv: str(kv[0])):
            name = str(names.get(strategy_id, "?"))[:28]
            print(_line(f"{name} ({str(strategy_id)[:8]})", compare(trades)))


async def main() -> int:
    engine = create_engine_for(get_settings().database_url)
    try:
        async with AsyncSession(engine) as session, session.begin():
            await _run(session)
    finally:
        await engine.dispose()
    print(
        "\nsummed = decision 17 (what the panel shows); exact = overlapping trades "
        "summed, later ones compounded. A negative gap means the panel shows less."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

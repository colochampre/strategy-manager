"""``by_pair``: a strategy's closed trades grouped per pair (design.md section
11; spec: performance-reporting requirement "Stats By Strategy and By Pair";
owner decisions 1 and 15).

**Per allocation first, then by pair.** The input is already one
``ClosedTrade`` per allocation (``derive_trades`` groups by ``allocation_id``,
never by symbol), so an allocation opened as ``SOLUSDT.P`` and closed by a
booked fill written as ``SOLUSDT`` arrives as ONE trade. This function then
keys each trade by ``market_key`` of its pair. It re-keys rather than trusting
``trade.pair``: a trade built by any other route with a raw spelling
(``SOLUSDT.P``, ``SOLUSDT_PERP``, ``solusdt``) still lands in the one row of
its market instead of opening a second one.

**No allowlist.** The function takes trades and nothing else. A pair removed
from the strategy's allowed pairs after it traded still shows its full history
(decision 15: the allowlist gates OPENS only). Nothing here can drop a pair
because of a setting that is read somewhere else.

**The figures per pair**, in the pool's native settlement currency (rule 7;
the caller passes one strategy's trades from one pool):

- ``trade_count`` and ``pnl`` count every closed trade of the pair, including
  those with no capital at open (their amount is real).
- ``value`` is the pair's contribution to the pool: each trade returns
  ``pnl / pool_total_at_open``, summed within a UTC day and compounded across
  days, the same algorithm as the pool's curve. It is ``None`` when no trade of
  the pair has a return, never a fabricated zero.
- ``win_count`` is the number of trades whose ``pnl`` is above zero and
  ``win_rate`` is ``win_count / trade_count`` (design.md, unit 12f addendum,
  section G). A PnL of exactly zero is not a win and counts in the total.
  Nothing is rounded here; the wire rounds.

Pure ``Decimal``, no framework, no I/O.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.performance.domain.closed_trade import ClosedTrade
from strategy_manager.performance.domain.curve import compound, daily_returns

_ZERO = Decimal(0)
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class PairStats:
    """One pair's closed trades: how many, their realized PnL in the pool's
    settlement currency, and their compounded return on pool capital (or
    ``None`` when none of them has a capital at open)."""

    pair: str
    trade_count: int
    pnl: Decimal
    value: Decimal | None
    win_count: int
    win_rate: Decimal


def by_pair(trades: Sequence[ClosedTrade]) -> tuple[PairStats, ...]:
    """Groups ``trades`` by the ``market_key`` of their pair, sorted by pair."""
    grouped: dict[str, list[ClosedTrade]] = defaultdict(list)
    for trade in trades:
        grouped[market_key(trade.pair)].append(trade)

    stats: list[PairStats] = []
    for pair in sorted(grouped):
        members = grouped[pair]
        points = compound(daily_returns(members))
        # A win is a PnL strictly above zero: a zero is not a win and still
        # counts in the total. ``members`` holds at least one trade, so the
        # divisor is never zero.
        win_count = sum(1 for t in members if t.pnl > _ZERO)
        stats.append(
            PairStats(
                pair=pair,
                trade_count=len(members),
                pnl=sum((t.pnl for t in members), _ZERO),
                value=points[-1].index - _ONE if points else None,
                win_count=win_count,
                win_rate=Decimal(win_count) / Decimal(len(members)),
            )
        )
    return tuple(stats)

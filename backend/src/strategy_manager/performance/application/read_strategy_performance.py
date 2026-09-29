"""``ReadStrategyPerformance``: one strategy's performance inside its pool
(design.md section 11 "Per strategy", section 14; tasks.md 3d.3, 3d.5).

**A strategy's curve is its contribution to the pool.** The algorithm is the
pool's own (``build_pool_performance``), run over this strategy's trades only,
and each trade still returns ``pnl / pool_total_at_open``: the POOL's capital
when the trade opened, not some capital the strategy "owns" (there is none;
that is the point of this app). The strategies' daily contributions therefore
add up exactly to the pool's ``R_d``, while the compounded strategy curves do
not multiply to the pool curve (design.md section 11).

**Scope (rule 7, decision 1).** The read takes the strategy and the pool it
lives in, asks the source for that one pool, and everything is in that pool's
settlement currency. See ``performance.application.scope`` for the refusals: a
row of another pool, or an allocation split across strategies, raises.

**Per pair** (``by_pair``) is independent of the strategy's allowed pairs: this
read is not given them (decision 15).

Exclusions are the strategy's own: its open allocations, its rehearsal fills
(``PoolFills.rehearsal_for``), its trades without capital or with an
unconverted fee, its unresolvable allocations. Logged as ``ReadPoolPerformance``
logs them, with the strategy id in the label.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import AllocationFillsSourcePort
from strategy_manager.performance.application.scope import (
    log_exclusions,
    pool_label,
    strategy_groups,
)
from strategy_manager.performance.domain.by_pair import PairStats, by_pair
from strategy_manager.performance.domain.curve import PoolPerformance, build_pool_performance
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StrategyPerformance:
    """``performance.pool`` is the strategy's own pool; every amount is in its
    settlement currency."""

    strategy_id: UUID
    performance: PoolPerformance
    by_pair: tuple[PairStats, ...]


class ReadStrategyPerformance:
    def __init__(self, fills: AllocationFillsSourcePort, clock: ClockPort) -> None:
        self._fills = fills
        self._clock = clock

    async def read(self, strategy_id: UUID, pool: PoolKey) -> StrategyPerformance:
        pool_fills = await self._fills.pool_fills(pool)
        groups = strategy_groups(pool, strategy_id, pool_fills.groups)

        derived = derive_trades(groups)
        report = build_pool_performance(
            pool, derived, pool_fills.rehearsal_for(strategy_id), self._clock.now()
        )
        log_exclusions(
            logger,
            f"{pool_label(pool)} strategy {strategy_id}",
            derived.unresolved_allocation_ids,
            report.exclusions,
        )
        return StrategyPerformance(strategy_id, report, by_pair(derived.closed))

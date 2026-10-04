"""``ReadPoolPerformance``: one pool's performance, composed from the ledger
(design.md section 11; tasks.md 3c.9).

**Rule 7 is enforced three ways here.** The signature takes exactly one
``PoolKey`` (all three of exchange, venue and settlement currency, so "the
exchange" or "all USDT" cannot be asked for); the port it reads through has no
method that returns more than one pool; and every row the source hands back is
checked against the requested pool BEFORE anything is derived, so a source that
misbehaves is refused rather than folded into a curve. The check is on rows, not
finished trades, because a stray opening leg would otherwise be counted as an
open trade of this pool without anyone noticing.

**What is logged, and why at that level.** The report already carries every
exclusion as a count, and that is the channel a person reads. The log adds the
detail the count cannot carry, at the level the condition deserves:

- ``WARNING`` with the allocation ids: an allocation whose symbol cannot be
  tested for closure. Never expected, and a bare count cannot be traced back to
  a row. Repeats on every read for as long as the row exists, which is right
  for a data-integrity fault. Not ``ERROR``: only ``ERROR`` reaches the
  operator's alerts, and a read model fires once per page view.
- ``INFO`` with the count: trades without capital at open, and trades with an
  unconverted fee. Both are steady state (the two reservations from before
  migration 0026 will be there forever) and both are already alerted at the
  cause: ``AllocateCapital`` logs an ERROR when a trade's capital is lost.
  Alerting on every read would train the operator to ignore alerts.
- Nothing when nothing was left out.
"""

import logging

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import AllocationFillsSourcePort
from strategy_manager.performance.application.scope import (
    log_exclusions,
    pool_label,
    require_live_only,
    require_single_pool,
)
from strategy_manager.performance.domain.curve import PoolPerformance, build_pool_performance
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)


class ReadPoolPerformance:
    def __init__(self, fills: AllocationFillsSourcePort, clock: ClockPort) -> None:
        self._fills = fills
        self._clock = clock

    async def read(self, pool: PoolKey) -> PoolPerformance:
        pool_fills = await self._fills.pool_fills(pool)
        require_single_pool(pool, pool_fills.groups)
        require_live_only(pool_fills.groups)

        derived = derive_trades(pool_fills.groups)
        report = build_pool_performance(
            pool, derived, pool_fills.rehearsal_fill_count, self._clock.now()
        )
        log_exclusions(
            logger, pool_label(pool), derived.unresolved_allocation_ids, report.exclusions
        )
        return report

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
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import AllocationFillsSourcePort
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.curve import PoolPerformance, build_pool_performance
from strategy_manager.performance.domain.derive_trade import derive_trades
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import InvariantViolation

logger = logging.getLogger(__name__)


class ReadPoolPerformance:
    def __init__(self, fills: AllocationFillsSourcePort, clock: ClockPort) -> None:
        self._fills = fills
        self._clock = clock

    async def read(self, pool: PoolKey) -> PoolPerformance:
        pool_fills = await self._fills.pool_fills(pool)
        _require_single_pool(pool, pool_fills.groups)

        derived = derive_trades(pool_fills.groups)
        report = build_pool_performance(
            pool, derived, pool_fills.rehearsal_fill_count, self._clock.now()
        )
        self._log_exclusions(pool, derived.unresolved_allocation_ids, report)
        return report

    @staticmethod
    def _log_exclusions(
        pool: PoolKey,
        unresolved: tuple[UUID, ...],
        report: PoolPerformance,
    ) -> None:
        label = f"{pool.exchange.value}/{pool.venue.value}/{pool.settlement_currency.value}"
        if unresolved:
            logger.warning(
                "performance %s: %d allocation(s) skipped because the symbol has no base "
                "currency in the pool's settlement currency, so their closure cannot be "
                "tested: %s",
                label,
                len(unresolved),
                ", ".join(str(a) for a in unresolved),
            )
        if report.exclusions.no_capital_at_open:
            logger.info(
                "performance %s: %d closed trade(s) with no capital at open are in the PnL "
                "amounts but not in the curve",
                label,
                report.exclusions.no_capital_at_open,
            )
        if report.exclusions.unconverted_fee:
            logger.info(
                "performance %s: %d closed trade(s) have an unconverted fee (a third "
                "currency); their PnL omits it",
                label,
                report.exclusions.unconverted_fee,
            )


def _require_single_pool(pool: PoolKey, groups: tuple[FillGroup, ...]) -> None:
    for group in groups:
        if (
            group.exchange != pool.exchange.value
            or group.venue != pool.venue.value
            or group.settlement_currency != pool.settlement_currency.value
        ):
            raise InvariantViolation(
                f"the fills source returned a row of pool ({group.exchange}, {group.venue}, "
                f"{group.settlement_currency}) for a read of ({pool.exchange.value}, "
                f"{pool.venue.value}, {pool.settlement_currency.value}); pools are never "
                "blended (CLAUDE.md rule 7)"
            )

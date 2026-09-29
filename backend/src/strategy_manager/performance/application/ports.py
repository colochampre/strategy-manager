"""Ports owned by ``performance``. The consumer owns the port; the
infrastructure adapter implements it (same direction as ``FillRecorderPort``).
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.closed_trade import FillGroup


@dataclass(frozen=True, slots=True)
class PoolFills:
    """Everything the ledger says about ONE pool.

    ``groups`` are the non-rehearsal aggregates. ``rehearsal_fill_count`` is
    how many DRY_RUN fills the source left out, so a figure that ignores them
    can still say how many it ignored.
    """

    groups: tuple[FillGroup, ...]
    rehearsal_fill_count: int
    rehearsal_by_strategy: tuple[tuple[UUID, int], ...] = ()

    def rehearsal_for(self, strategy_id: UUID) -> int:
        """How many rehearsal fills of ONE strategy the source left out. A
        strategy's report states its own count, never the pool's."""
        return sum(count for sid, count in self.rehearsal_by_strategy if sid == strategy_id)


class AllocationFillsSourcePort(Protocol):
    """Reads a pool's ledger as per-(allocation, strategy, side, fee currency)
    aggregates.

    Takes exactly one ``PoolKey``. There is no method that reads more than one
    pool, so a cross-pool total (CLAUDE.md rule 7) cannot be requested through
    this port.
    """

    async def pool_fills(self, pool: PoolKey) -> PoolFills: ...

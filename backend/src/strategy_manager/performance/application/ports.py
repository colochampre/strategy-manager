"""Ports owned by ``performance``. The consumer owns the port; the
infrastructure adapter implements it (same direction as ``FillRecorderPort``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.operation import PricingFacts


@dataclass(frozen=True, slots=True)
class PoolFills:
    """Everything the ledger says about ONE pool.

    ``groups`` are the non-rehearsal aggregates: the only set any total reads.
    ``rehearsal_groups`` are the DRY_RUN aggregates, kept apart so that no
    figure can include them by accident; the trades list is their one reader,
    and only when it is asked for them. ``rehearsal_fill_count`` is how many
    DRY_RUN fills the scope holds, so a figure that ignores them can still say
    how many it ignored.
    """

    groups: tuple[FillGroup, ...]
    rehearsal_fill_count: int
    rehearsal_by_strategy: tuple[tuple[UUID, int], ...] = ()
    rehearsal_groups: tuple[FillGroup, ...] = ()

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


class RehearsalPricingSourcePort(Protocol):
    """What the ledger and the signals say about how rehearsal operations were
    priced: for the allocations asked, in ONE call, the price each one's alert
    carried and the price range of each side's fills.

    An allocation the source holds no facts for is simply absent from the answer;
    the caller decides what that means. Takes the strategy as well as the ids, so
    another strategy's allocation is never answered through this strategy's read.
    """

    async def pricing_facts(
        self, pool: PoolKey, strategy_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PricingFacts]: ...

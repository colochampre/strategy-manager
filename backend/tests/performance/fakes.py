"""In-memory stand-ins for ``performance`` ports."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import PoolFills
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.operation import PricingFacts


class FakeFillsSource:
    """Returns whatever it was given for ANY pool it is asked about, so a test
    can hand ``ReadPoolPerformance`` a source that misbehaves (returns another
    pool's rows) and see the read refuse. Records each pool it was asked for."""

    def __init__(
        self,
        groups: list[FillGroup],
        rehearsal_fill_count: int = 0,
        rehearsal_by_strategy: dict[UUID, int] | None = None,
        rehearsal_groups: list[FillGroup] | None = None,
    ) -> None:
        self._groups = groups
        self._rehearsal_fill_count = rehearsal_fill_count
        self._rehearsal_by_strategy = tuple((rehearsal_by_strategy or {}).items())
        self._rehearsal_groups = tuple(rehearsal_groups or ())
        self.asked: list[PoolKey] = []

    async def pool_fills(self, pool: PoolKey) -> PoolFills:
        self.asked.append(pool)
        return PoolFills(
            tuple(self._groups),
            self._rehearsal_fill_count,
            self._rehearsal_by_strategy,
            self._rehearsal_groups,
        )


class FakePricingSource:
    """Answers the pricing facts it was given and records each call, so a test can
    count the calls and see which ids were asked for.

    ``default`` answers any id ``facts`` does not name; without one such an id
    is absent from the answer, as a source with no row for it would leave it."""

    def __init__(
        self,
        facts: Mapping[UUID, PricingFacts] | None = None,
        *,
        default: PricingFacts | None = None,
    ) -> None:
        self._facts = dict(facts or {})
        self._default = default
        self.calls: list[tuple[PoolKey, UUID, list[UUID]]] = []

    async def pricing_facts(
        self, pool: PoolKey, strategy_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PricingFacts]:
        self.calls.append((pool, strategy_id, list(allocation_ids)))
        answer: dict[UUID, PricingFacts] = {}
        for allocation_id in allocation_ids:
            if allocation_id in self._facts:
                answer[allocation_id] = self._facts[allocation_id]
            elif self._default is not None:
                answer[allocation_id] = self._default
        return answer


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

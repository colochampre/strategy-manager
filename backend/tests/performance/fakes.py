"""In-memory stand-ins for ``performance`` ports."""

from datetime import datetime
from uuid import UUID

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.application.ports import PoolFills
from strategy_manager.performance.domain.closed_trade import FillGroup


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


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

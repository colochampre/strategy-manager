"""``SqlAlchemyRehearsalPricingSource``: how the opening fills of rehearsal
operations were priced, from stored rows alone (design.md, addendum "a
strategy's operations", sections C and E).

Stub: answers no facts yet (task 9p.4.21 writes the statement).
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.performance.domain.operation import PricingFacts


class SqlAlchemyRehearsalPricingSource:
    """Implements ``RehearsalPricingSourcePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def pricing_facts(
        self, pool: PoolKey, strategy_id: UUID, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, PricingFacts]:
        return {}

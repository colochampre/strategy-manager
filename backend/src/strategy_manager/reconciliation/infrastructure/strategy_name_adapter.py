"""``StrategyNameAdapter``: implements
``reconciliation.application.ports.StrategyNamesPort`` with ONE read-only
statement for every allocation id of the confirmed-discrepancies view (design
PR 15 addendum § G), in the manner of ``allocation_owner_adapter.py``.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.reconciliation.application.ports import AllocationStrategy
from strategy_manager.strategies.infrastructure.models import StrategyRow


class StrategyNameAdapter:
    """Implements ``reconciliation.application.ports.StrategyNamesPort``. An
    allocation with no reservation, or whose strategy row is gone, is absent
    from the answer (an inner join): the caller serves it as ``null`` and logs
    the fault."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def strategies_for(
        self, allocation_ids: Sequence[UUID]
    ) -> Mapping[UUID, AllocationStrategy]:
        if not allocation_ids:
            return {}
        stmt = (
            select(ReservationRow.id, StrategyRow.id, StrategyRow.name)
            .join(StrategyRow, StrategyRow.id == ReservationRow.strategy_id)
            .where(ReservationRow.id.in_(list(allocation_ids)))
        )
        return {
            allocation_id: AllocationStrategy(strategy_id, name)
            for allocation_id, strategy_id, name in (await self._session.execute(stmt)).all()
        }

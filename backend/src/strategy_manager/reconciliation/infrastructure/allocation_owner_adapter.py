"""``AllocationOwnerAdapter``: implements
``reconciliation.application.ports.AllocationOwnerPort`` by reading
``reservations.strategy_id`` directly -- the same cross-module read
``SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol``
already performs by importing ``ReservationRow`` from ``allocation``'s own
infrastructure models.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.shared.domain.errors import InvariantViolation


class AllocationOwnerAdapter:
    """Implements ``reconciliation.application.ports.AllocationOwnerPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def strategy_for(self, allocation_id: UUID) -> UUID:
        result = await self._session.execute(
            select(ReservationRow.strategy_id).where(ReservationRow.id == allocation_id)
        )
        strategy_id = result.scalar_one_or_none()
        if strategy_id is None:
            raise InvariantViolation(f"no reservation {allocation_id}")
        return strategy_id

"""``SqlAlchemyAllocationMode``: implements ``AllocationModePort`` against the
``reservations`` table, which recorded the mode in the pool lock."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode


class SqlAlchemyAllocationMode:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mode_of(self, user_id: UUID, allocation_id: UUID) -> Mode:
        recorded = (
            await self._session.execute(
                select(ReservationRow.mode).where(
                    ReservationRow.id == allocation_id, ReservationRow.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if recorded is None:
            raise InvariantViolation(
                f"allocation {allocation_id} is not a reservation of user "
                f"{str(user_id)[:8]}, so nothing says which mode it runs in"
            )
        return Mode(recorded)

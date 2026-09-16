"""Implements ``execution.application.ports.ReservationGatewayPort`` against
the ``reservations`` table ``allocation`` already owns — provider owns the
adapter, execution is the consumer that declared the port (design.md's
cross-module wiring rule).
"""

from datetime import datetime
from uuid import UUID

from strategy_manager.allocation.domain.reservation import ReservationStatus
from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.application.ports import ReservationSnapshot


class ReservationGatewayAdapter:
    """Implements ``execution.application.ports.ReservationGatewayPort``."""

    def __init__(self, repository: SqlAlchemyReservationRepository) -> None:
        self._repository = repository

    async def get_for_update(self, reservation_id: UUID) -> ReservationSnapshot:
        reservation = await self._repository.get_for_update(reservation_id)
        return ReservationSnapshot(
            id=reservation.id,
            strategy_id=reservation.strategy_id,
            exchange=reservation.pool_key.exchange.value,
            venue=reservation.pool_key.venue.value,
            settlement_currency=reservation.pool_key.settlement_currency.value,
            amount=reservation.amount,
            status=reservation.status.value,
            expires_at=reservation.expires_at,
        )

    async def mark(self, reservation_id: UUID, status: str, at: datetime) -> None:
        await self._repository.mark(reservation_id, ReservationStatus(status), at)

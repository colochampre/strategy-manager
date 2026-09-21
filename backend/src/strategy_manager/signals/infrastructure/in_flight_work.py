"""Implements ``signals.application.ports.InFlightWorkPort`` by composing
``execution``'s SUBMITTED-attempt read and ``allocation``'s PENDING-
reservation read (design.md § "In flight vs orphan"). Provider owns the
adapter, ``signals`` is the consumer that declared the port -- mirrors
``allocation.infrastructure.reservation_gateway.ReservationGatewayAdapter``'s
same cross-module wiring shape, one level up: this adapter composes TWO
provider repositories rather than one, because neither ``execution`` nor
``allocation`` holds the whole answer alone.
"""

from datetime import datetime
from uuid import UUID

from strategy_manager.allocation.infrastructure.repository import SqlAlchemyReservationRepository
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.signals.application.ports import PoolKey


class InFlightWorkAdapter:
    """Implements ``signals.application.ports.InFlightWorkPort``."""

    def __init__(
        self,
        attempts: SqlAlchemyExecutionAttemptRepository,
        reservations: SqlAlchemyReservationRepository,
    ) -> None:
        self._attempts = attempts
        self._reservations = reservations

    async def in_flight(
        self, pool: PoolKey, strategy_id: UUID, symbol: str, now: datetime
    ) -> bool:
        exchange, venue, settlement_currency = pool

        submitted = await self._attempts.submitted_for_strategy_symbol(
            exchange, venue, settlement_currency, strategy_id, symbol
        )
        if submitted:
            return True

        return await self._reservations.has_pending_for_strategy(
            exchange, venue, settlement_currency, strategy_id, now
        )

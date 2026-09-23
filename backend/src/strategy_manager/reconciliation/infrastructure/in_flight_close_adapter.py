"""``InFlightCloseAdapter``: implements
``reconciliation.application.ports.InFlightClosePort`` by delegating to the
EXISTING ``SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol``
-- no new SQL (design.md § 7). Mirrors
``signals.infrastructure.in_flight_work.InFlightWorkAdapter``'s identical
cross-module wiring shape and its typing convention: the constructor takes
the concrete provider repository directly, not a narrow structural
Protocol, matching that adapter's own precedent.
"""

from uuid import UUID

from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.reconciliation.application.ports import PoolKey


class InFlightCloseAdapter:
    """Implements ``reconciliation.application.ports.InFlightClosePort``."""

    def __init__(self, repository: SqlAlchemyExecutionAttemptRepository) -> None:
        self._repository = repository

    async def submitted_for(self, pool: PoolKey, strategy_id: UUID, symbol: str) -> bool:
        exchange, venue, settlement_currency = pool
        return await self._repository.submitted_for_strategy_symbol(
            exchange, venue, settlement_currency, strategy_id, symbol
        )

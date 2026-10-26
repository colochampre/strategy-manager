"""``InFlightCloseAdapter``: implements
``reconciliation.application.ports.InFlightClosePort`` by delegating to the
EXISTING ``SqlAlchemyExecutionAttemptRepository.submitted_for_strategy_symbol``
-- no new SQL for the check itself (design.md § 7). Mirrors
``signals.infrastructure.in_flight_work.InFlightWorkAdapter``'s cross-module
wiring shape.

**INTERIM owner (multi-user design AD8; tasks.md B.8).** The repository reads
one user's attempts, and a booking proposal does not carry its user yet (U6
adds it). Until then the user is the strategy's author: in PR B every attempt
of a strategy is its author's, because a signal is executed in the author's
pool. A strategy that is gone has no attempts, so the answer is ``False``.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.strategies.infrastructure.models import StrategyRow


class InFlightCloseAdapter:
    """Implements ``reconciliation.application.ports.InFlightClosePort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = SqlAlchemyExecutionAttemptRepository(session)

    async def submitted_for(self, pool: PoolKey, strategy_id: UUID, symbol: str) -> bool:
        author_id = (
            await self._session.execute(
                select(StrategyRow.author_id).where(StrategyRow.id == strategy_id)
            )
        ).scalar_one_or_none()
        if author_id is None:
            return False
        exchange, venue, settlement_currency = pool
        return await self._repository.submitted_for_strategy_symbol(
            author_id, exchange, venue, settlement_currency, strategy_id, symbol
        )

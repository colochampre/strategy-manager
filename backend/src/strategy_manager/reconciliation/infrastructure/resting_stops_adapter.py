"""``RestingStopsAdapter``: implements ``reconciliation.application.ports.RestingStopsPort``
(subscriber-safety SS.7).

Which markets of one user's pool have a protective stop that is still ``RESTING``. The stop
row records no settlement currency of its own, so the pool is read through the opening
attempt it protects, which does. Only the given user's stops count (multi-user AD8), and only
that pool's. ``reconciliation`` reads ``execution``'s tables through the session directly, as
``SystemOrderIdsAdapter`` does for attempts.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.protective_stop import StopStatus
from strategy_manager.execution.infrastructure.models import (
    ExecutionAttemptRow,
    ProtectiveStopRow,
)
from strategy_manager.reconciliation.application.ports import PoolKey


class RestingStopsAdapter:
    """Implements ``RestingStopsPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resting_symbols(self, user_id: UUID, pool: PoolKey) -> list[str]:
        exchange, venue, settlement_currency = pool
        result = await self._session.execute(
            select(ProtectiveStopRow.symbol)
            .join(
                ExecutionAttemptRow,
                ExecutionAttemptRow.id == ProtectiveStopRow.execution_attempt_id,
            )
            .where(
                ProtectiveStopRow.user_id == user_id,
                ProtectiveStopRow.status == StopStatus.RESTING.value,
                ProtectiveStopRow.exchange == exchange,
                ProtectiveStopRow.venue == venue,
                ExecutionAttemptRow.settlement_currency == settlement_currency,
            )
            .distinct()
        )
        return list(result.scalars())

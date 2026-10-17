"""``SystemOrderIdsAdapter``: implements
``reconciliation.application.ports.SystemOrderIdsPort`` (owner decision 66 Q2,
2026-10-16; design.md PR 15 addendum C8).

Whether any of a set of venue order ids is the ``exchange_order_id`` of an
``execution_attempts`` row of the SAME ``(exchange, venue,
settlement_currency)`` -- a fill of an order THIS system placed. One statement
for the whole set. An attempt with no order id (the venue never accepted it)
matches nothing, because ``NULL = ANY(...)`` is never true.

``SqlAlchemyExecutionAttemptRepository`` has no query for this and lives in
``execution``, so the adapter reads ``ExecutionAttemptRow`` through the session
directly, the way ``AllocationOwnerAdapter`` reads ``ReservationRow``.
"""

from collections.abc import Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.reconciliation.application.ports import PoolKey


class SystemOrderIdsAdapter:
    """Implements ``reconciliation.application.ports.SystemOrderIdsPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def holds_any(self, pool: PoolKey, exchange_order_ids: Sequence[str]) -> bool:
        if not exchange_order_ids:
            return False
        exchange, venue, settlement_currency = pool
        result = await self._session.execute(
            select(
                exists().where(
                    ExecutionAttemptRow.exchange == exchange,
                    ExecutionAttemptRow.venue == venue,
                    ExecutionAttemptRow.settlement_currency == settlement_currency,
                    ExecutionAttemptRow.exchange_order_id.in_(list(exchange_order_ids)),
                )
            )
        )
        return bool(result.scalar_one())

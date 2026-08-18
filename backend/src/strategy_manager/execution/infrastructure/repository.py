"""SQLAlchemy implementation of ``ExecutionAttemptRepositoryPort`` against
the ``execution_attempts`` table (migration ``0005``).
"""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow


class SqlAlchemyExecutionAttemptRepository:
    """Implements ``execution.application.ports.ExecutionAttemptRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, attempt: ExecutionAttempt) -> None:
        self._session.add(
            ExecutionAttemptRow(
                id=attempt.id,
                reservation_id=attempt.reservation_id,
                venue=attempt.venue,
                settlement_currency=attempt.settlement_currency,
                symbol=attempt.symbol,
                side=attempt.side.value,
                quantity=attempt.quantity,
                status=attempt.status.value,
                client_order_id=attempt.client_order_id,
                exchange_order_id=attempt.exchange_order_id,
                error=attempt.error,
            )
        )
        await self._session.flush()

    async def mark_filled(self, attempt_id: UUID, exchange_order_id: str) -> None:
        await self._session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.id == attempt_id)
            .values(status=ExecutionStatus.FILLED.value, exchange_order_id=exchange_order_id)
        )

    async def mark_failed(self, attempt_id: UUID, error: str) -> None:
        await self._session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.id == attempt_id)
            .values(status=ExecutionStatus.FAILED.value, error=error)
        )

"""SQLAlchemy implementation of ``ExecutionAttemptRepositoryPort`` against
the ``execution_attempts`` table (migrations ``0005`` and ``0011``).
"""

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt, ExecutionStatus
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow
from strategy_manager.shared.domain.errors import InvariantViolation


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
                quote_amount=attempt.quote_amount,
                status=attempt.status.value,
                client_order_id=attempt.client_order_id,
                exchange_order_id=attempt.exchange_order_id,
                error=attempt.error,
            )
        )
        await self._session.flush()

    async def get(self, attempt_id: UUID) -> ExecutionAttempt:
        row = (
            await self._session.execute(
                select(ExecutionAttemptRow).where(ExecutionAttemptRow.id == attempt_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise InvariantViolation(f"no execution attempt {attempt_id}")

        return ExecutionAttempt(
            id=row.id,
            reservation_id=row.reservation_id,
            venue=row.venue,
            settlement_currency=row.settlement_currency,
            symbol=row.symbol,
            side=OrderSide(row.side),
            quantity=row.quantity,
            quote_amount=row.quote_amount,
            status=ExecutionStatus(row.status),
            client_order_id=row.client_order_id,
            exchange_order_id=row.exchange_order_id,
            error=row.error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def mark_placed(self, attempt_id: UUID, exchange_order_id: str) -> None:
        """Records the exchange's id for an already-SUBMITTED attempt.

        Bookkeeping, not a precondition: settlement finds the order by the
        client order id, so losing this write to a crash costs traceability
        and nothing else.
        """
        await self._session.execute(
            update(ExecutionAttemptRow)
            .where(ExecutionAttemptRow.id == attempt_id)
            .values(exchange_order_id=exchange_order_id)
        )

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

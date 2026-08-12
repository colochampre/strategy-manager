"""SQLAlchemy implementation of ``SignalRepositoryPort``.

``ON CONFLICT (strategy_id, idempotency_key) DO NOTHING`` makes the insert
idempotent at the database level; a conflict falls back to a lookup of the
already-persisted row (spec: signal-ingress § Idempotent Signal Persistence).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.signals.application.ports import InsertOutcome
from strategy_manager.signals.domain.signal import WebhookSignal
from strategy_manager.signals.infrastructure.models import SignalRow


class SqlAlchemySignalRepository:
    """Implements ``SignalRepositoryPort`` against the ``signals`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_or_get(self, signal: WebhookSignal) -> InsertOutcome:
        stmt = (
            pg_insert(SignalRow)
            .values(
                strategy_id=signal.strategy_id,
                idempotency_key=signal.idempotency_key.value,
                raw_payload=signal.raw_payload,
                status=signal.status.value,
                action=signal.action,
                contracts=signal.contracts,
                position_size=signal.position_size,
                price=signal.price,
                symbol=signal.symbol,
                signal_type=signal.signal_type,
            )
            .on_conflict_do_nothing(index_elements=["strategy_id", "idempotency_key"])
            .returning(SignalRow.id)
        )
        result = await self._session.execute(stmt)
        row = result.first()
        if row is not None:
            return InsertOutcome(signal_id=row.id, inserted=True)

        signal_id = await self._existing_signal_id(signal.strategy_id, signal.idempotency_key.value)
        return InsertOutcome(signal_id=signal_id, inserted=False)

    async def _existing_signal_id(self, strategy_id: UUID, idempotency_key: str) -> UUID:
        result = await self._session.execute(
            select(SignalRow.id).where(
                SignalRow.strategy_id == strategy_id,
                SignalRow.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one()

"""SQLAlchemy implementation of ``SignalRepositoryPort``.

``ON CONFLICT (strategy_id, idempotency_key) DO NOTHING`` makes the insert
idempotent at the database level; a conflict falls back to a lookup of the
already-persisted row (spec: signal-ingress § Idempotent Signal Persistence).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.domain.market_symbol import market_spellings
from strategy_manager.signals.application.ports import InsertOutcome
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal
from strategy_manager.signals.infrastructure.models import SignalRow


def _to_domain(row: SignalRow) -> WebhookSignal:
    return WebhookSignal(
        id=row.id,
        strategy_id=row.strategy_id,
        idempotency_key=IdempotencyKey(row.idempotency_key),
        action=row.action,
        contracts=row.contracts,
        position_size=row.position_size,
        price=row.price,
        symbol=row.symbol,
        signal_type=row.signal_type,
        raw_payload=row.raw_payload,
        received_at=row.received_at,
        status=SignalStatus(row.status),
        job_id=row.job_id,
    )


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

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None:
        row = await self._session.get(SignalRow, signal_id)
        return _to_domain(row) if row is not None else None

    async def find_prior(
        self, strategy_id: UUID, symbol: str, before: datetime
    ) -> WebhookSignal | None:
        """Backed by ``ix_signals_strategy_symbol_received_at`` (migration
        ``0002``) — the index this exact query was built for."""

        row = (
            await self._session.execute(
                select(SignalRow)
                .where(
                    SignalRow.strategy_id == strategy_id,
                    SignalRow.symbol == symbol,
                    SignalRow.received_at < before,
                )
                .order_by(SignalRow.received_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row is not None else None

    async def has_newer(self, strategy_id: UUID, symbol: str, received_at: datetime) -> bool:
        """Implements ``SignalRepositoryPort.has_newer`` — merged across
        every spelling ``symbol`` wears, exactly like
        ``execution.infrastructure.repository``'s
        ``submitted_for_strategy_symbol`` merges the same way for the
        Existing-Position Guard.
        """
        spellings = list(market_spellings(symbol))
        result = await self._session.execute(
            select(SignalRow.id)
            .where(
                SignalRow.strategy_id == strategy_id,
                func.upper(SignalRow.symbol).in_(spellings),
                SignalRow.received_at > received_at,
            )
            .limit(1)
        )
        return result.first() is not None

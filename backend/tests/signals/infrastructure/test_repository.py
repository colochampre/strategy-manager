"""Integration test against a real PostgreSQL database (strategy_manager_test).

Covers spec: signal-ingress § Idempotent Signal Persistence — the DB-level
guarantee that ``ON CONFLICT DO NOTHING`` produces no second row.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.signals.domain.signal import IdempotencyKey, WebhookSignal
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.signals.infrastructure.repository import SqlAlchemySignalRepository

pytestmark = pytest.mark.integration


def _signal(strategy_id: object, idempotency_key: str) -> WebhookSignal:
    return WebhookSignal(
        strategy_id=strategy_id,  # type: ignore[arg-type]
        idempotency_key=IdempotencyKey(idempotency_key),
        action="buy",
        contracts=Decimal("10"),
        position_size=Decimal("10"),
        price=Decimal("50000.5"),
        symbol="BTCUSDT",
        signal_type="a6a28229-9286-463f-99e8-5f48eb597d19",
        raw_payload={"symbol": "BTCUSDT"},
    )


async def test_on_conflict_do_nothing_insert_produces_no_second_row_on_duplicate_key(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    key = "k" * 20

    async with pg_session_factory() as session:
        repository = SqlAlchemySignalRepository(session)
        first = await repository.insert_or_get(_signal(strategy_id, key))
        await session.commit()

    async with pg_session_factory() as session:
        repository = SqlAlchemySignalRepository(session)
        second = await repository.insert_or_get(_signal(strategy_id, key))
        await session.commit()

    assert first.inserted is True
    assert second.inserted is False
    assert second.signal_id == first.signal_id

    async with pg_session_factory() as session:
        count = await session.execute(
            select(func.count())
            .select_from(SignalRow)
            .where(SignalRow.strategy_id == strategy_id, SignalRow.idempotency_key == key)
        )
        assert count.scalar_one() == 1

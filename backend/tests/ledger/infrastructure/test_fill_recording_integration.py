"""Integration test: a successful fill recorded through
``FillRecorderPort``/``RecordFill``/``SqlAlchemyLedgerRepository`` persists a
``ledger_entries`` row carrying ``allocation_id``, ``strategy_id`` and the
owning pool (tasks.md 5.13; spec: trade-ledger § Ledger Row Content,
trade-execution § Fill Recording) [DB].
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.models import LedgerEntryRow
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration


async def test_successful_fill_is_recorded_in_full(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    strategy_id = uuid4()
    signal_id = uuid4()
    reservation_id = uuid4()
    attempt_id = uuid4()

    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    await seed_signal(
        pg_session_factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key="k1"
    )
    await seed_reservation(
        pg_session_factory,
        reservation_id=reservation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
    )
    await seed_execution_attempt(
        pg_session_factory, attempt_id=attempt_id, reservation_id=reservation_id
    )

    async with pg_session_factory() as session:
        record_fill = RecordFill(SqlAlchemyLedgerRepository(session))
        await record_fill.record(
            FillRecord(
                strategy_id=strategy_id,
                allocation_id=reservation_id,
                execution_attempt_id=attempt_id,
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="BTCUSDT",
                side="BUY",
                quantity=Decimal("0.004"),
                price=Decimal("50000"),
                fee=Decimal("0.02"),
                fee_currency="USDT",
                notional=Decimal("200"),
                exchange_order_id="ex-order-1",
                exchange_fill_id="ex-fill-1",
                filled_at=datetime(2026, 8, 18, tzinfo=UTC),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()

    async with pg_session_factory() as session:
        row = (
            await session.execute(
                select(LedgerEntryRow).where(LedgerEntryRow.execution_attempt_id == attempt_id)
            )
        ).scalar_one()

    assert row.strategy_id == strategy_id
    assert row.allocation_id == reservation_id
    assert row.venue == "usdt-m"
    assert row.settlement_currency == "USDT"
    assert row.usd_rate_at_fill == Decimal("1")

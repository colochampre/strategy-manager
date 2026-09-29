"""Decision 28, composed: ``main.assert_dry_run_matches_ledger`` against real
PostgreSQL, seeded through the real ledger. No credential, no network (rule 1):
the check reads two tables and needs neither the vault nor a venue.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.execution.application.ports import FillRecord
from strategy_manager.execution.domain.fill import REHEARSAL_FILL_ID_PREFIX
from strategy_manager.ledger.application.record_fill import RecordFill
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.domain.startup_refusal import StartupRefused
from tests.ledger.infrastructure.conftest import (
    seed_execution_attempt,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration


async def _seed_open_position(
    session_factory: async_sessionmaker[AsyncSession], *, rehearsal: bool
) -> tuple[UUID, str]:
    strategy_id, signal_id = uuid4(), uuid4()
    allocation_id, attempt_id = uuid4(), uuid4()
    await seed_strategy(session_factory, strategy_id=strategy_id)
    await seed_signal(
        session_factory,
        signal_id=signal_id,
        strategy_id=strategy_id,
        idempotency_key=f"k-{signal_id}",
    )
    await seed_reservation(
        session_factory,
        reservation_id=allocation_id,
        strategy_id=strategy_id,
        signal_id=signal_id,
        status="FILLED",
    )
    await seed_execution_attempt(
        session_factory,
        attempt_id=attempt_id,
        reservation_id=allocation_id,
        status="FILLED",
    )
    prefix = REHEARSAL_FILL_ID_PREFIX if rehearsal else "live-"
    async with session_factory() as session:
        await RecordFill(SqlAlchemyLedgerRepository(session)).record(
            FillRecord(
                exchange="bybit",
                strategy_id=strategy_id,
                allocation_id=allocation_id,
                execution_attempt_id=attempt_id,
                venue="usdt-m",
                settlement_currency="USDT",
                symbol="SOLUSDT.P",
                side="BUY",
                quantity=Decimal("0.5"),
                price=Decimal("100"),
                fee=Decimal("0"),
                fee_currency="USDT",
                notional=Decimal("50"),
                exchange_order_id=f"order-{uuid4()}",
                exchange_fill_id=f"{prefix}{uuid4()}",
                filled_at=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
                usd_rate_at_fill=Decimal("1"),
            )
        )
        await session.commit()
    return allocation_id, f"strategy-{strategy_id}"


async def test_a_live_start_over_an_open_rehearsal_position_is_refused(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id, strategy_name = await _seed_open_position(pg_session_factory, rehearsal=True)

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await main.assert_dry_run_matches_ledger(
            dry_run=False, session_factory_override=pg_session_factory
        )

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    for expected in (strategy_name, "bybit/usdt-m/USDT", "SOLUSDT.P", str(allocation_id)):
        assert expected in errors[0]


async def test_a_dry_run_start_over_an_open_live_position_is_refused(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id, _ = await _seed_open_position(pg_session_factory, rehearsal=False)

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await main.assert_dry_run_matches_ledger(
            dry_run=True, session_factory_override=pg_session_factory
        )

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert str(allocation_id) in errors[0]


async def test_a_start_in_the_matching_mode_logs_nothing(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_open_position(pg_session_factory, rehearsal=True)

    with caplog.at_level(logging.DEBUG, logger="strategy_manager.execution"):
        await main.assert_dry_run_matches_ledger(
            dry_run=True, session_factory_override=pg_session_factory
        )

    assert caplog.records == []


async def test_an_empty_ledger_starts_in_either_mode(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for dry_run in (True, False):
        await main.assert_dry_run_matches_ledger(
            dry_run=dry_run, session_factory_override=pg_session_factory
        )

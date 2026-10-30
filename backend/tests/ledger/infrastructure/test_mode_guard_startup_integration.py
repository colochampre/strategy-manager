"""Decision 28 and AD7, composed: ``main.assert_modes_match_ledger`` against real
PostgreSQL, seeded through the real ledger. No credential, no network (rule 1):
the check reads the ledger, the attempts and one column of the vault's table,
and opens no key.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager import main
from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
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
from tests.owner import OWNER_ID

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
async def _no_key_left_behind(pg_session_factory: Factory) -> AsyncIterator[None]:
    """A fixture truncates the ledger, never the vault's table."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()
    yield
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await session.commit()


async def _seed_key(factory: Factory, *, trade_capable: bool, is_active: bool = True) -> None:
    async with factory() as session:
        session.add(
            ExchangeCredentialRow(
                user_id=OWNER_ID,
                exchange="bybit",
                label="default",
                is_active=is_active,
                wrapped_dek=b"x",
                dek_nonce=b"x",
                api_key_ciphertext=b"x",
                api_key_nonce=b"x",
                api_secret_ciphertext=b"x",
                api_secret_nonce=b"x",
                api_key_last4="abcd",
                trade_capable=trade_capable,
                trade_capability_source="VERIFIED",
                trade_confirmed_at=None,
                withdraw_check="VERIFIED",
                withdraw_confirmed_at=None,
                validated_at=datetime.now(UTC),
                internal_transfer=True,
            )
        )
        await session.commit()


async def _seed_open_position(
    session_factory: Factory, *, rehearsal: bool, mode: str
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
        mode=mode,
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
                user_id=OWNER_ID,
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


async def test_a_live_record_over_a_rehearsal_position_is_refused(
    pg_session_factory: Factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_key(pg_session_factory, trade_capable=True)
    allocation_id, strategy_name = await _seed_open_position(
        pg_session_factory, rehearsal=True, mode="LIVE"
    )

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await main.assert_modes_match_ledger(session_factory_override=pg_session_factory)

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    for expected in (strategy_name, "bybit/usdt-m/USDT", "SOLUSDT.P", str(allocation_id)):
        assert expected in errors[0]


async def test_a_simulated_record_over_a_live_position_is_refused(
    pg_session_factory: Factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    allocation_id, _ = await _seed_open_position(
        pg_session_factory, rehearsal=False, mode="SIMULATION"
    )

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await main.assert_modes_match_ledger(session_factory_override=pg_session_factory)

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert str(allocation_id) in errors[0]


async def test_positions_in_both_modes_agreeing_with_their_records_log_nothing(
    pg_session_factory: Factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _seed_key(pg_session_factory, trade_capable=True)
    await _seed_open_position(pg_session_factory, rehearsal=True, mode="SIMULATION")
    await _seed_open_position(pg_session_factory, rehearsal=False, mode="LIVE")

    with caplog.at_level(logging.DEBUG, logger="strategy_manager.execution"):
        await main.assert_modes_match_ledger(session_factory_override=pg_session_factory)

    assert caplog.records == []


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(None, id="no-key"),
        pytest.param({"trade_capable": False}, id="read-only-key"),
        pytest.param({"trade_capable": True, "is_active": False}, id="superseded-key"),
    ],
)
async def test_a_real_position_no_key_can_close_is_refused_naming_its_user(
    pg_session_factory: Factory,
    caplog: pytest.LogCaptureFixture,
    key: dict[str, bool] | None,
) -> None:
    if key is not None:
        await _seed_key(pg_session_factory, **key)
    await _seed_open_position(pg_session_factory, rehearsal=False, mode="LIVE")

    with caplog.at_level(logging.INFO), pytest.raises(StartupRefused):
        await main.assert_modes_match_ledger(session_factory_override=pg_session_factory)

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert f"user {OWNER_ID}: 1 allocation(s) on bybit" in errors[0]


async def test_a_simulated_position_needs_no_key(pg_session_factory: Factory) -> None:
    await _seed_open_position(pg_session_factory, rehearsal=True, mode="SIMULATION")

    await main.assert_modes_match_ledger(session_factory_override=pg_session_factory)


async def test_an_empty_ledger_starts(pg_session_factory: Factory) -> None:
    await main.assert_modes_match_ledger(session_factory_override=pg_session_factory)

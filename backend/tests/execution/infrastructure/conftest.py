"""Fixtures for ``execution.infrastructure.repository`` integration tests
against a real PostgreSQL database. Mirrors
``tests/ledger/infrastructure/conftest.py`` and
``tests/signals/infrastructure/conftest.py``, trimmed to only what
``SqlAlchemyExecutionAttemptRepository``'s own tests need: ``strategies``,
``reservations`` and ``execution_attempts``.
"""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow  # noqa: F401
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import Base
from strategy_manager.shared.infrastructure.models import JobRow  # noqa: F401  (registers table)
from strategy_manager.signals.infrastructure.models import SignalRow  # noqa: F401
from strategy_manager.strategies.infrastructure.models import StrategyRow
from tests.pg_schema import rebuild_schema_once

TEST_DB_NAME = "strategy_manager_test"

_test_db_ready = False

SEEDED_POOLS = [
    {
        "exchange": "bybit",
        "venue": "usdt-m",
        "settlement_currency": "USDT",
        "min_order_size": Decimal("5"),
    },
]


def _test_database_url(dev_url: str) -> str:
    test_url = re.sub(r"/[^/?]+(\?.*)?$", rf"/{TEST_DB_NAME}\1", dev_url)
    if test_url == dev_url:
        raise RuntimeError(
            "TEST_DATABASE_URL must not match settings.database_url (the dev database)"
        )
    return test_url


async def _ensure_test_database_exists(dev_url: str) -> None:
    global _test_db_ready
    if _test_db_ready:
        return
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    maintenance_dsn = re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()
    _test_db_ready = True


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    settings = get_settings()
    test_url = _test_database_url(settings.database_url)
    await _ensure_test_database_exists(settings.database_url)

    engine = create_async_engine(test_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await rebuild_schema_once(conn)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "TRUNCATE execution_attempts, reservations, signals, strategies, "
                "capital_pools, jobs RESTART IDENTITY CASCADE"
            )
        )
        for pool in SEEDED_POOLS:
            await conn.execute(
                text(
                    "INSERT INTO capital_pools "
                    "(exchange, venue, settlement_currency, min_order_size) "
                    "VALUES (:exchange, :venue, :settlement_currency, :min_order_size)"
                ),
                pool,
            )

    yield engine

    await engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)


async def seed_strategy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    strategy_id: UUID,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    fill_mode: str = "PARTIAL",
    enabled: bool = True,
) -> None:
    async with session_factory() as session:
        session.add(
            StrategyRow(
                id=strategy_id,
                name=f"strategy-{strategy_id}",
                exchange=exchange,
                venue=venue,
                settlement_currency=settlement_currency,
                enabled=enabled,
                fill_mode=fill_mode,
            )
        )
        await session.commit()


async def seed_signal(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    signal_id: UUID,
    strategy_id: UUID,
    idempotency_key: str,
) -> None:
    async with session_factory() as session:
        session.add(
            SignalRow(
                id=signal_id,
                strategy_id=strategy_id,
                idempotency_key=idempotency_key,
                raw_payload={},
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal("1"),
                price=Decimal("1"),
                symbol="BTCUSDT",
                signal_type=str(strategy_id),
            )
        )
        await session.commit()


async def seed_reservation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    reservation_id: UUID,
    strategy_id: UUID,
    signal_id: UUID,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    amount: Decimal = Decimal("200"),
    status: str = "SUBMITTED",
    expires_at: datetime | None = None,
) -> None:
    resolved_expires_at = (
        expires_at if expires_at is not None else datetime.now(UTC) + timedelta(hours=1)
    )
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO reservations "
                "(id, strategy_id, signal_id, exchange, venue, settlement_currency, "
                "amount, status, expires_at) "
                "VALUES (:id, :strategy_id, :signal_id, :exchange, :venue, "
                ":settlement_currency, :amount, :status, :expires_at)"
            ),
            {
                "id": reservation_id,
                "strategy_id": strategy_id,
                "signal_id": signal_id,
                "exchange": exchange,
                "venue": venue,
                "settlement_currency": settlement_currency,
                "amount": amount,
                "status": status,
                "expires_at": resolved_expires_at,
            },
        )
        await session.commit()


async def seed_execution_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    attempt_id: UUID,
    reservation_id: UUID | None = None,
    closes_allocation_id: UUID | None = None,
    exchange: str = "bybit",
    venue: str = "usdt-m",
    settlement_currency: str = "USDT",
    symbol: str = "BTCUSDT",
    status: str = "SUBMITTED",
    created_at: datetime | None = None,
) -> None:
    """Seeds either kind of attempt (migration ``0012``): an opening one bound
    to the reservation it spends, or a closing one bound to the allocation it
    unwinds. Exactly one of the two ids belongs on a row.

    ``created_at`` is settable directly (bypassing the ``server_default``)
    so ``latest_close_for``'s ordering tests have a deterministic boundary
    instead of racing the wall clock across separate transactions.
    """
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO execution_attempts "
                "(id, reservation_id, closes_allocation_id, exchange, venue, "
                "settlement_currency, symbol, side, quantity, status, client_order_id"
                + (", created_at" if created_at is not None else "")
                + ") "
                "VALUES (:id, :reservation_id, :closes_allocation_id, :exchange, :venue, "
                ":settlement_currency, :symbol, 'BUY', 0.004, :status, "
                ":client_order_id"
                + (", :created_at" if created_at is not None else "")
                + ")"
            ),
            {
                "id": attempt_id,
                "reservation_id": reservation_id,
                "closes_allocation_id": closes_allocation_id,
                "exchange": exchange,
                "venue": venue,
                "settlement_currency": settlement_currency,
                "symbol": symbol,
                "status": status,
                "client_order_id": f"client-{attempt_id}",
                **({"created_at": created_at} if created_at is not None else {}),
            },
        )
        await session.commit()

"""Fixtures for reconciliation integration tests against a real PostgreSQL
database. Mirrors ``tests/strategies/infrastructure/conftest.py``.

Uses ``Base.metadata.create_all`` rather than an ``alembic upgrade head``
database, exactly like every other module's own lightweight router/auth
fixture: what these tests exercise is the ROUTER and its auth wiring, not the
table's constraints -- those already have a dedicated Tier B suite in
``test_discrepancy_repository_integration.py``.

Also carries ``strategies``/``signals``/``reservations``/``execution_attempts``
and their own ``seed_*`` helpers, duplicated from
``tests/ledger/infrastructure/conftest.py`` rather than imported from it --
the same per-module duplication ``tests/signals/infrastructure/conftest.py``
already uses for its own copy. Unit 4a's ``AllocationOwnerAdapter`` (reads
``reservations.strategy_id``) needs the FK chain those tables provide, which
this package's own fixture never carried before.
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

from strategy_manager.allocation.infrastructure.models import ReservationRow  # noqa: F401
from strategy_manager.execution.infrastructure.models import ExecutionAttemptRow  # noqa: F401
from strategy_manager.reconciliation.infrastructure.models import (  # noqa: F401
    ReconciliationDiscrepancyRow,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import Base
from strategy_manager.signals.infrastructure.models import SignalRow
from strategy_manager.strategies.infrastructure.models import StrategyRow
from tests.pg_schema import rebuild_schema_once

TEST_DB_NAME = "strategy_manager_test"

_test_db_ready = False

# Only the pool ``AllocationOwnerAdapter``'s own tests need -- unlike
# ``tests/ledger/infrastructure/conftest.py``'s full ``SEEDED_POOLS``, this
# package has no COIN-M/spot test relying on the other three.
_SEEDED_POOL = {
    "exchange": "bybit",
    "venue": "usdt-m",
    "settlement_currency": "USDT",
    "min_order_size": Decimal("5"),
}


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
        # ``Base.metadata`` carries column shape only (see the model's own
        # docstring) -- the migration is the source of truth for table-level
        # constraints. ``upsert_open``'s ``ON CONFLICT`` needs this partial
        # unique index to exist to have a target to infer, exactly the index
        # migration ``0020`` creates, so it is (re)created here too.
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_reconciliation_open_per_symbol "
                "ON reconciliation_discrepancies "
                "(exchange, venue, settlement_currency, symbol) "
                "WHERE resolved_at IS NULL"
            )
        )
        # CASCADE: migration 0023 added booking_proposals' FK to this table
        # (no ON DELETE CASCADE there -- see that migration's docstring --
        # but a plain TRUNCATE still refuses without one here, and this
        # fixture's own booking_proposals rows, if any, are exactly as
        # disposable as the reconciliation_discrepancies rows it already
        # truncates every test).
        await conn.execute(text("TRUNCATE reconciliation_discrepancies CASCADE"))
        # The FK chain ``AllocationOwnerAdapter``'s own tests seed --
        # mirrors ``tests/ledger/infrastructure/conftest.py``'s identical
        # TRUNCATE/reseed shape for the same tables.
        await conn.execute(
            text(
                "TRUNCATE execution_attempts, reservations, signals, strategies, "
                "capital_pools RESTART IDENTITY CASCADE"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO capital_pools "
                "(exchange, venue, settlement_currency, min_order_size) "
                "VALUES (:exchange, :venue, :settlement_currency, :min_order_size)"
            ),
            _SEEDED_POOL,
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
    """Duplicated from ``tests/ledger/infrastructure/conftest.py``'s helper
    of the same name -- see this file's own docstring for why."""
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
    resolved_expires_at = expires_at if expires_at is not None else datetime.now(UTC) + timedelta(
        hours=1
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
) -> None:
    """Seeds either kind of attempt (migration ``0012``): an opening one
    bound to the reservation it spends, or a closing one bound to the
    allocation it unwinds. Exactly one of the two ids belongs on a row."""
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO execution_attempts "
                "(id, reservation_id, closes_allocation_id, exchange, venue, "
                "settlement_currency, symbol, side, quantity, status, client_order_id) "
                "VALUES (:id, :reservation_id, :closes_allocation_id, :exchange, :venue, "
                ":settlement_currency, :symbol, 'BUY', 0.004, :status, "
                ":client_order_id)"
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
            },
        )
        await session.commit()

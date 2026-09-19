"""Fixtures for reconciliation integration tests against a real PostgreSQL
database. Mirrors ``tests/strategies/infrastructure/conftest.py``.

Uses ``Base.metadata.create_all`` rather than an ``alembic upgrade head``
database, exactly like every other module's own lightweight router/auth
fixture: what these tests exercise is the ROUTER and its auth wiring, not the
table's constraints -- those already have a dedicated Tier B suite in
``test_discrepancy_repository_integration.py``.
"""

import re
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.reconciliation.infrastructure.models import (  # noqa: F401
    ReconciliationDiscrepancyRow,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import Base
from tests.pg_schema import rebuild_schema_once

TEST_DB_NAME = "strategy_manager_test"

_test_db_ready = False


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
        await conn.execute(text("TRUNCATE reconciliation_discrepancies"))

    yield engine

    await engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

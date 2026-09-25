"""Fixtures for `accounts/application` integration tests against a real
PostgreSQL database.

Reuses ``tests.accounts.infrastructure.conftest``'s database-creation
helpers (same physical ``strategy_manager_test`` database, same
``rebuild_schema_once`` guard), but seeds NOTHING: unlike that fixture's
fixed four pools, PR 3 unit 1b.9's pool-reload tests need full control over
``capital_pools`` rows and their ``enabled`` flag, seeded per test.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import Base
from strategy_manager.strategies.infrastructure.models import StrategyRow  # noqa: F401
from tests.accounts.infrastructure.conftest import (
    _ensure_test_database_exists,
    _test_database_url,
)
from tests.pg_schema import rebuild_schema_once


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
                "TRUNCATE strategies, capital_pools, exchange_credentials, "
                "pool_balance_snapshots, jobs RESTART IDENTITY CASCADE"
            )
        )

    yield engine

    await engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

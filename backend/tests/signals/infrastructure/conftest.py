"""Fixtures for signals integration tests against a real PostgreSQL database.

Mirrors ``tests/shared/infrastructure/conftest.py``: a session/connection per
test against ``strategy_manager_test``, never the dev database.
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

from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import Base
from strategy_manager.shared.infrastructure.models import JobRow  # noqa: F401  (registers table)
from strategy_manager.signals.infrastructure.models import SignalRow  # noqa: F401

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
        # Drop and recreate ``signals`` unconditionally: a stale table from an
        # earlier schema iteration (e.g. missing the composite unique
        # constraint) would otherwise survive ``create_all``'s checkfirst.
        # ``CASCADE`` is required since slice 4: ``reservations`` carries a
        # foreign key into ``signals``, so a plain ``DROP TABLE`` now fails
        # with "other objects depend on it" — both tables are recreated by
        # ``create_all`` immediately below regardless.
        await conn.execute(text("DROP TABLE IF EXISTS signals CASCADE"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("TRUNCATE signals, jobs RESTART IDENTITY CASCADE"))

    yield engine

    await engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

"""Fixtures for accounts integration tests against a real PostgreSQL database.

Seeds the four configured pools directly (mirrors migration ``0003``'s seed
step) since these tests exercise ORM models via ``Base.metadata.create_all``,
not the Alembic migration chain — the real chain is verified separately by
``alembic upgrade head``.
"""

import re
from collections.abc import AsyncIterator
from decimal import Decimal

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
from strategy_manager.strategies.infrastructure.models import StrategyRow  # noqa: F401
from tests.pg_schema import rebuild_schema_once

TEST_DB_NAME = "strategy_manager_test"

_test_db_ready = False

# Mirrors migration 0003's seed rows (design.md § SQL Schema and Migration Map).
SEEDED_POOLS = [
    {"venue": "spot", "settlement_currency": "USDT", "min_order_size": Decimal("10")},
    {"venue": "usdt-m", "settlement_currency": "USDT", "min_order_size": Decimal("5")},
    {"venue": "coin-m", "settlement_currency": "BTC", "min_order_size": Decimal("0.0001")},
    {"venue": "coin-m", "settlement_currency": "ETH", "min_order_size": Decimal("0.001")},
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
        await conn.execute(text("TRUNCATE strategies, capital_pools RESTART IDENTITY CASCADE"))
        for pool in SEEDED_POOLS:
            await conn.execute(
                text(
                    "INSERT INTO capital_pools (venue, settlement_currency, min_order_size) "
                    "VALUES (:venue, :settlement_currency, :min_order_size)"
                ),
                pool,
            )

    yield engine

    await engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)

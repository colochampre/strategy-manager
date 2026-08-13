"""Integration test: the collision check against the four real seeded pools
(spec: capital-allocation § Startup Lock-Key Collision Invariant; tasks.md
3.14). Only calls ``SELECT hashtext(...)`` — no schema/tables required, so
this connects straight to ``strategy_manager_test`` without the
create-all fixture used elsewhere (see
``tests/accounts/infrastructure/conftest.py`` for why that database name is
used instead of the shared ``strategy_manager_test``).
"""

import re
from collections.abc import AsyncIterator
from decimal import Decimal

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.infrastructure.lock_key_invariant import (
    assert_pool_lock_keys_distinct,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.domain.money import Currency, Venue

pytestmark = pytest.mark.integration

TEST_DB_NAME = "strategy_manager_test"
_test_db_ready = False

_CONFIGURED_POOLS = [
    PoolConfig(venue=Venue.SPOT, settlement_currency=Currency.USDT, min_order_size=Decimal("10")),
    PoolConfig(
        venue=Venue.USDT_M, settlement_currency=Currency.USDT, min_order_size=Decimal("5")
    ),
    PoolConfig(
        venue=Venue.COIN_M, settlement_currency=Currency.BTC, min_order_size=Decimal("0.0001")
    ),
    PoolConfig(
        venue=Venue.COIN_M, settlement_currency=Currency.ETH, min_order_size=Decimal("0.001")
    ),
]


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
async def pg_connection() -> AsyncIterator[AsyncConnection]:
    settings = get_settings()
    test_url = re.sub(r"/[^/?]+(\?.*)?$", rf"/{TEST_DB_NAME}\1", settings.database_url)
    await _ensure_test_database_exists(settings.database_url)

    engine = create_async_engine(test_url, pool_pre_ping=True)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def test_collision_check_passes_for_the_four_real_seeded_pools(
    pg_connection: AsyncConnection,
) -> None:
    await assert_pool_lock_keys_distinct(pg_connection, _CONFIGURED_POOLS)  # no raise


async def test_coin_m_btc_and_eth_share_k1_but_differ_in_k2(
    pg_connection: AsyncConnection,
) -> None:
    btc = await pg_connection.execute(
        text("SELECT hashtext(:venue), hashtext(:currency)"),
        {"venue": "coin-m", "currency": "BTC"},
    )
    eth = await pg_connection.execute(
        text("SELECT hashtext(:venue), hashtext(:currency)"),
        {"venue": "coin-m", "currency": "ETH"},
    )
    btc_k1, btc_k2 = btc.one()
    eth_k1, eth_k2 = eth.one()

    assert btc_k1 == eth_k1 == 1937348485
    assert btc_k2 == -1182514593
    assert eth_k2 == 273220054

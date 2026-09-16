"""Tier B: raw ``UPDATE``, ``DELETE`` and ``TRUNCATE`` on ``ledger_entries``
each raise ``restrict_violation`` (tasks.md 5.12; spec: trade-ledger §
Append-Only Enforcement) [DB].

This module gets its own freshly created database, migrated with the real
``alembic upgrade head`` (not ``Base.metadata.create_all``, which knows
nothing about raw-SQL triggers) — the only way to actually exercise the
``fn_ledger_append_only()`` triggers migration ``0005`` installs. The
database is dropped at teardown (design.md's "Tier B" test isolation note).

The DB create/migrate/drop steps run through plain ``asyncio.run`` calls
inside a *synchronous*, module-scoped fixture, deliberately avoiding any
async fixture at module scope — pytest-asyncio's per-test event loop (this
project's ``asyncio_mode = auto``) does not compose safely with an
async fixture shared across tests that each get a fresh loop.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_TIER_B_DB_NAME = "strategy_manager_test_ledger_guard"


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


def _database_url(dev_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{name}\1", dev_url)


async def _drop_database_if_exists(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def _create_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _run_alembic_upgrade(database_url: str) -> None:
    """Runs migrations in a subprocess so alembic's own ``asyncio.run`` never
    collides with the test's already-running event loop."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed for Tier B database:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def tier_b_database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    database_url = _database_url(dev_url, _TIER_B_DB_NAME)

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _TIER_B_DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _TIER_B_DB_NAME))
    # migration 0003 already seeds the four configured pools, including
    # spot/USDT — reused below by every test, no additional seeding needed.
    _run_alembic_upgrade(database_url)

    yield database_url

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _TIER_B_DB_NAME))


@pytest.fixture
async def tier_b_connection(tier_b_database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(tier_b_database_url, pool_pre_ping=True)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


def _pgcode(error: DBAPIError) -> str | None:
    """The PostgreSQL SQLSTATE of the underlying driver error — proves the
    trigger raised exactly ``restrict_violation`` (``23001``), not merely
    some exception with a matching message."""

    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


async def _seed_full_chain(conn: AsyncConnection) -> UUID:
    strategy_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, 'pionex', 'spot', 'USDT', true, 'PARTIAL')"
        ),
        {"id": strategy_id, "name": f"strategy-{strategy_id}"},
    )
    signal_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) "
            "VALUES (:id, :strategy_id, 'k1', '{}', 'buy', 1, 1, 1, 'BTCUSDT', :signal_type)"
        ),
        {"id": signal_id, "strategy_id": strategy_id, "signal_type": str(strategy_id)},
    )
    reservation_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO reservations "
            "(id, strategy_id, signal_id, exchange, venue, settlement_currency, "
            "amount, status, expires_at) "
            "VALUES (:id, :strategy_id, :signal_id, 'pionex', 'spot', 'USDT', 200, "
            "'SUBMITTED', now() + interval '1 hour')"
        ),
        {"id": reservation_id, "strategy_id": strategy_id, "signal_id": signal_id},
    )
    attempt_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution_attempts (id, reservation_id, venue, settlement_currency, "
            "symbol, side, quantity, status, client_order_id) "
            "VALUES (:id, :reservation_id, 'spot', 'USDT', 'BTCUSDT', 'BUY', 0.004, "
            "'SUBMITTED', :client_order_id)"
        ),
        {"id": attempt_id, "reservation_id": reservation_id, "client_order_id": f"c-{attempt_id}"},
    )
    ledger_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO ledger_entries (id, strategy_id, allocation_id, execution_attempt_id, "
            "venue, settlement_currency, symbol, side, quantity, price, fee, fee_currency, "
            "notional, exchange_order_id, exchange_fill_id, filled_at, usd_rate_at_fill) "
            "VALUES (:id, :strategy_id, :allocation_id, :execution_attempt_id, 'spot', 'USDT', "
            "'BTCUSDT', 'BUY', 0.004, 50000, 0.02, 'USDT', 200, :exchange_order_id, "
            ":exchange_fill_id, now(), 1)"
        ),
        {
            "id": ledger_id,
            "strategy_id": strategy_id,
            "allocation_id": reservation_id,
            "execution_attempt_id": attempt_id,
            "exchange_order_id": f"ex-order-{ledger_id}",
            "exchange_fill_id": f"ex-fill-{ledger_id}",
        },
    )
    await conn.commit()
    return ledger_id


async def test_update_is_rejected(
    tier_b_connection: AsyncConnection, tier_b_database_url: str
) -> None:
    ledger_id = await _seed_full_chain(tier_b_connection)

    with pytest.raises(DBAPIError, match="(?i)append-only") as exc_info:
        await tier_b_connection.execute(
            text("UPDATE ledger_entries SET fee = fee + 1 WHERE id = :id"), {"id": ledger_id}
        )
    assert _pgcode(exc_info.value) == "23001"  # restrict_violation
    await tier_b_connection.rollback()

    engine = create_async_engine(tier_b_database_url, pool_pre_ping=True)
    async with engine.connect() as verify_conn:
        fee = (
            await verify_conn.execute(
                text("SELECT fee FROM ledger_entries WHERE id = :id"), {"id": ledger_id}
            )
        ).scalar_one()
        assert fee == Decimal("0.02")  # unchanged
    await engine.dispose()


async def test_delete_is_rejected(
    tier_b_connection: AsyncConnection, tier_b_database_url: str
) -> None:
    ledger_id = await _seed_full_chain(tier_b_connection)

    with pytest.raises(DBAPIError, match="(?i)append-only") as exc_info:
        await tier_b_connection.execute(
            text("DELETE FROM ledger_entries WHERE id = :id"), {"id": ledger_id}
        )
    assert _pgcode(exc_info.value) == "23001"  # restrict_violation
    await tier_b_connection.rollback()

    engine = create_async_engine(tier_b_database_url, pool_pre_ping=True)
    async with engine.connect() as verify_conn:
        count = (
            await verify_conn.execute(
                text("SELECT COUNT(*) FROM ledger_entries WHERE id = :id"), {"id": ledger_id}
            )
        ).scalar_one()
        assert count == 1  # still present
    await engine.dispose()


async def test_truncate_is_rejected(
    tier_b_connection: AsyncConnection, tier_b_database_url: str
) -> None:
    await _seed_full_chain(tier_b_connection)

    engine = create_async_engine(tier_b_database_url, pool_pre_ping=True)
    async with engine.connect() as count_conn:
        count_before = (
            await count_conn.execute(text("SELECT COUNT(*) FROM ledger_entries"))
        ).scalar_one()

    with pytest.raises(DBAPIError, match="(?i)append-only") as exc_info:
        await tier_b_connection.execute(text("TRUNCATE ledger_entries"))
    assert _pgcode(exc_info.value) == "23001"  # restrict_violation
    await tier_b_connection.rollback()

    async with engine.connect() as verify_conn:
        count_after = (
            await verify_conn.execute(text("SELECT COUNT(*) FROM ledger_entries"))
        ).scalar_one()
        assert count_after == count_before  # no rows removed, table contains multiple rows
        assert count_after > 0
    await engine.dispose()

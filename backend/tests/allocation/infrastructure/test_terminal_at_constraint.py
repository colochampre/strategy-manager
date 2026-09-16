"""Migration ``0008``'s CHECK constraints, proven against a genuinely migrated
database (tasks.md 6.3).

``Base.metadata.create_all`` builds tables and columns — never CHECK
constraints, never partial indexes, never triggers. Every other allocation
integration test therefore runs against a schema that is *missing* these
constraints, which means a green suite says nothing about whether they hold.
That asymmetry is the dangerous part: production would enforce a rule the tests
never exercise. This module closes it, the same way the ledger's append-only
guard does for its triggers.

The database is created, migrated with the real ``alembic upgrade head`` and
dropped, once for this module.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_DB_NAME = "strategy_manager_test_reservation_constraints"


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


async def _recreate_database(dev_url: str) -> None:
    conn = await asyncpg.connect(_maintenance_dsn(dev_url))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{_DB_NAME}"')
    finally:
        await conn.close()


async def _drop_database(dev_url: str) -> None:
    conn = await asyncpg.connect(_maintenance_dsn(dev_url))
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_DB_NAME}" WITH (FORCE)')
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
        raise RuntimeError(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")


@pytest.fixture(scope="module")
def migrated_database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    url = re.sub(r"/[^/?]+(\?.*)?$", rf"/{_DB_NAME}\1", dev_url)

    asyncio.run(_recreate_database(dev_url))
    _run_alembic_upgrade(url)
    yield url
    asyncio.run(_drop_database(dev_url))


@pytest.fixture
async def conn(migrated_database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(migrated_database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _seed_active_reservation(conn: AsyncConnection) -> str:
    """Inserts the FK chain a reservation needs, then a PENDING reservation."""

    strategy_id, signal_id, reservation_id = uuid4(), uuid4(), uuid4()
    await conn.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, 'pionex', 'spot', 'USDT', true, 'PARTIAL')"
        ),
        {"id": strategy_id, "name": f"s-{strategy_id}"},
    )
    await conn.execute(
        text(
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) "
            "VALUES (:id, :sid, :key, '{}', 'buy', 1, 1, 1, 'BTCUSDT', :sig_type)"
        ),
        {
            "id": signal_id,
            "sid": strategy_id,
            "key": f"k-{signal_id}",
            "sig_type": str(strategy_id),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO reservations "
            "(id, strategy_id, signal_id, exchange, venue, settlement_currency, "
            "amount, status, expires_at) VALUES "
            "(:id, :sid, :sig, 'pionex', 'spot', 'USDT', :amount, 'PENDING', "
            "now() + interval '1 hour')"
        ),
        {
            "id": reservation_id,
            "sid": strategy_id,
            "sig": signal_id,
            "amount": Decimal("100"),
        },
    )
    await conn.commit()
    return str(reservation_id)


async def test_an_active_reservation_cannot_carry_a_terminal_timestamp(
    conn: AsyncConnection,
) -> None:
    """The pairing invariant. The sweep is a set-based UPDATE that never loads
    an aggregate, so the domain cannot enforce this — only the database can."""

    reservation_id = await _seed_active_reservation(conn)

    with pytest.raises(IntegrityError):
        await conn.execute(
            text("UPDATE reservations SET terminal_at = now() WHERE id = :id"),
            {"id": reservation_id},
        )
        await conn.commit()
    await conn.rollback()


async def test_terminating_sets_status_and_timestamp_together(conn: AsyncConnection) -> None:
    """The legitimate path the constraint must not block."""

    reservation_id = await _seed_active_reservation(conn)

    await conn.execute(
        text(
            "UPDATE reservations SET status = 'EXPIRED', terminal_at = now(), "
            "release_reason = 'EXPIRED_BY_SWEEPER' WHERE id = :id"
        ),
        {"id": reservation_id},
    )
    await conn.commit()

    status = (
        await conn.execute(
            text("SELECT status FROM reservations WHERE id = :id"), {"id": reservation_id}
        )
    ).scalar_one()
    assert status == "EXPIRED"


async def test_an_unknown_release_reason_is_rejected(conn: AsyncConnection) -> None:
    reservation_id = await _seed_active_reservation(conn)

    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                "UPDATE reservations SET status = 'EXPIRED', terminal_at = now(), "
                "release_reason = 'BECAUSE_I_SAID_SO' WHERE id = :id"
            ),
            {"id": reservation_id},
        )
        await conn.commit()
    await conn.rollback()

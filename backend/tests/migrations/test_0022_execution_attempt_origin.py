"""Migration ``0022`` -- ``execution_attempts.origin`` (design.md § 2;
spec: trade-execution § Execution Attempt Origin).

Runs against a real ``alembic upgrade head`` database, following the same
pattern as ``tests/migrations/test_0021_execution_attempts_live_close.py``.
The database is dropped at teardown.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.execution.infrastructure.repository import (
    CLIENT_ORDER_ID_UNIQUE_CONSTRAINT,
)
from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_execution_attempt_origin"

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}


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


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs an alembic subcommand in a subprocess so alembic's own
    ``asyncio.run`` never collides with the test's already-running loop."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    return result


def _run_alembic_ok(database_url: str, *args: str) -> None:
    result = _run_alembic(database_url, *args)
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, _DB_NAME)

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic_ok(url, "upgrade", "head")

    yield url

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _seed_allocation(conn: AsyncConnection) -> UUID:
    """Seeds a strategy + signal + reservation and returns the reservation
    id -- the allocation a VENUE-origin closing attempt's
    ``closes_allocation_id`` refers to."""
    strategy_id, signal_id, allocation_id = uuid4(), uuid4(), uuid4()
    await conn.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, :exchange, :venue, :settlement_currency, true, 'PARTIAL')"
        ),
        {"id": strategy_id, "name": f"strategy-{strategy_id}", **_POOL},
    )
    await conn.execute(
        text(
            "INSERT INTO signals "
            "(id, strategy_id, idempotency_key, raw_payload, action, contracts, "
            "position_size, price, symbol, signal_type) "
            "VALUES (:id, :strategy_id, :idempotency_key, '{}', 'buy', 1, 1, 1, "
            "'BTCUSDT', :signal_type)"
        ),
        {
            "id": signal_id,
            "strategy_id": strategy_id,
            "idempotency_key": f"k-{signal_id}",
            "signal_type": str(strategy_id),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO reservations "
            "(id, strategy_id, signal_id, exchange, venue, settlement_currency, "
            "amount, status, expires_at) "
            "VALUES (:id, :strategy_id, :signal_id, :exchange, :venue, "
            ":settlement_currency, 100, 'FILLED', now() + interval '1 hour')"
        ),
        {"id": allocation_id, "strategy_id": strategy_id, "signal_id": signal_id, **_POOL},
    )
    return allocation_id


async def _insert_attempt(
    conn: AsyncConnection,
    *,
    allocation_id: UUID,
    origin: str | None,
) -> UUID:
    """Inserts a closing attempt, naming ``origin`` explicitly in the column
    list only when given -- ``None`` omits the column entirely, exercising
    the ADD COLUMN default rather than an application-supplied value."""
    attempt_id = uuid4()
    columns = (
        "id, closes_allocation_id, exchange, venue, settlement_currency, "
        "symbol, side, quantity, status, client_order_id"
    )
    values = (
        ":id, :allocation_id, :exchange, :venue, :settlement_currency, "
        "'BTCUSDT', 'SELL', 0.004, :status, :client_order_id"
    )
    params: dict[str, object] = {
        "id": attempt_id,
        "allocation_id": allocation_id,
        "status": "FILLED",
        "client_order_id": f"client-{attempt_id}",
        **_POOL,
    }
    if origin is not None:
        columns += ", origin"
        values += ", :origin"
        params["origin"] = origin
    await conn.execute(
        text(f"INSERT INTO execution_attempts ({columns}) VALUES ({values})"),  # noqa: S608
        params,
    )
    return attempt_id


async def test_client_order_id_constraint_name_matches_recorded_constant(
    conn: AsyncConnection,
) -> None:
    """Blocker (a): the live unique constraint name is recorded verbatim as
    a constant so ``ApproveBooking`` (Unit 6a) can identify a replayed
    approval by CONSTRAINT NAME, never by message text."""
    found = (
        await conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid = "
                "'execution_attempts'::regclass AND contype = 'u' "
                "AND conname = :name"
            ),
            {"name": CLIENT_ORDER_ID_UNIQUE_CONSTRAINT},
        )
    ).scalar_one_or_none()
    assert found == CLIENT_ORDER_ID_UNIQUE_CONSTRAINT


def test_upgrade_backfills_system_default(database_url: str) -> None:
    """Every pre-0022 row is correct by construction -- built by
    ``PlaceOrder`` or ``ClosePosition``, both of which submit to a venue
    (design.md § 2). Downgrades to 0021 (where the column does not exist
    yet), inserts a row the old way, upgrades back to head, and asserts the
    ADD COLUMN default backfilled it as ``SYSTEM`` without the migration
    touching a single row itself."""

    async def _insert_pre_migration_attempt() -> UUID:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                allocation_id = await _seed_allocation(connection)
                attempt_id = await _insert_attempt(
                    connection, allocation_id=allocation_id, origin=None
                )
                await connection.commit()
            return attempt_id
        finally:
            await engine.dispose()

    async def _read_origin(attempt_id: UUID) -> str:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return (
                    await connection.execute(
                        text("SELECT origin FROM execution_attempts WHERE id = :id"),
                        {"id": attempt_id},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()

    _run_alembic_ok(database_url, "downgrade", "0021")
    attempt_id = asyncio.run(_insert_pre_migration_attempt())
    _run_alembic_ok(database_url, "upgrade", "head")

    assert asyncio.run(_read_origin(attempt_id)) == "SYSTEM"


def test_downgrade_refuses_while_venue_rows_exist_naming_ids(database_url: str) -> None:
    """Unlike 0021's ``force_failed_close_drop``, this downgrade offers no
    force flag at all: a VENUE attempt always has ledger rows behind it, and
    no flag should offer to delete history the append-only trigger itself
    forbids deleting (design.md § 2)."""

    async def _insert_venue_attempt() -> UUID:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                allocation_id = await _seed_allocation(connection)
                attempt_id = await _insert_attempt(
                    connection, allocation_id=allocation_id, origin="VENUE"
                )
                await connection.commit()
            return attempt_id
        finally:
            await engine.dispose()

    attempt_id = asyncio.run(_insert_venue_attempt())

    refused = _run_alembic(database_url, "downgrade", "0021")

    assert refused.returncode != 0
    combined = refused.stdout + refused.stderr
    assert str(attempt_id) in combined
    assert "1 execution_attempts row" in combined

    # Unlike 0021's ``force_failed_close_drop``, no ``-x`` argument makes
    # this downgrade succeed -- the function reads no ``context.get_x_argument``
    # at all, so passing one changes nothing about the outcome.
    still_refused = _run_alembic(
        database_url, "-x", "force_venue_drop=1", "downgrade", "0021"
    )
    assert still_refused.returncode != 0


def test_downgrade_succeeds_with_zero_venue_rows(database_url: str) -> None:
    """With no VENUE-origin row left to lose, the downgrade is unconditional
    -- ``DROP COLUMN`` needs no guard of its own."""

    async def _clear_execution_attempts() -> None:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                for table in ("execution_attempts", "reservations", "signals", "strategies"):
                    await connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608
                await connection.commit()
        finally:
            await engine.dispose()

    async def _origin_column_exists() -> bool:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return bool(
                    (
                        await connection.execute(
                            text(
                                "SELECT 1 FROM information_schema.columns WHERE "
                                "table_name = 'execution_attempts' AND "
                                "column_name = 'origin'"
                            )
                        )
                    ).scalar_one_or_none()
                )
        finally:
            await engine.dispose()

    asyncio.run(_clear_execution_attempts())

    _run_alembic_ok(database_url, "downgrade", "0021")
    assert asyncio.run(_origin_column_exists()) is False

    _run_alembic_ok(database_url, "upgrade", "head")
    assert asyncio.run(_origin_column_exists()) is True

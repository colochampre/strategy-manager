"""Tier B: migration ``0021`` -- ``execution_attempts.closes_allocation_id``
stops being UNIQUE system-wide (design.md § S6; spec: trade-execution §
Retryable Close, Single In-Flight Attempt).

Runs against a real ``alembic upgrade head`` database (the only way to
exercise a partial unique index), following the same pattern as
``tests/migrations/test_0020_reconciliation_discrepancies.py``. The database
is dropped at teardown.

Every test reuses the ``(pionex, spot, USDT)`` pool migration ``0003``
already seeds and migration ``0017``/``0018`` already backfilled -- no
additional pool needs inserting.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_execution_live_close"

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
    """Seeds a strategy + signal + reservation against the pre-seeded pool
    and returns the reservation id -- the allocation a closing attempt's
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


async def _insert_close(
    conn: AsyncConnection, *, allocation_id: UUID, status: str
) -> UUID:
    attempt_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution_attempts "
            "(id, closes_allocation_id, exchange, venue, settlement_currency, "
            "symbol, side, quantity, status, client_order_id) "
            "VALUES (:id, :allocation_id, :exchange, :venue, :settlement_currency, "
            "'BTCUSDT', 'SELL', 0.004, :status, :client_order_id)"
        ),
        {
            "id": attempt_id,
            "allocation_id": allocation_id,
            "status": status,
            "client_order_id": f"client-{attempt_id}",
            **_POOL,
        },
    )
    return attempt_id


async def test_a_failed_close_does_not_block_a_new_submitted_close(
    conn: AsyncConnection,
) -> None:
    allocation_id = await _seed_allocation(conn)
    await _insert_close(conn, allocation_id=allocation_id, status="FAILED")
    await conn.commit()

    await _insert_close(conn, allocation_id=allocation_id, status="SUBMITTED")
    await conn.commit()

    count = (
        await conn.execute(
            text(
                "SELECT count(*) FROM execution_attempts "
                "WHERE closes_allocation_id = :id"
            ),
            {"id": allocation_id},
        )
    ).scalar_one()
    assert count == 2


async def test_two_submitted_closes_on_one_allocation_still_violate(
    conn: AsyncConnection,
) -> None:
    allocation_id = await _seed_allocation(conn)
    await _insert_close(conn, allocation_id=allocation_id, status="SUBMITTED")
    await conn.commit()

    with pytest.raises(IntegrityError):
        await _insert_close(conn, allocation_id=allocation_id, status="SUBMITTED")
    await conn.rollback()


async def test_a_filled_close_does_not_block_a_residual_close(
    conn: AsyncConnection,
) -> None:
    allocation_id = await _seed_allocation(conn)
    await _insert_close(conn, allocation_id=allocation_id, status="FILLED")
    await conn.commit()

    await _insert_close(conn, allocation_id=allocation_id, status="SUBMITTED")
    await conn.commit()

    count = (
        await conn.execute(
            text(
                "SELECT count(*) FROM execution_attempts "
                "WHERE closes_allocation_id = :id"
            ),
            {"id": allocation_id},
        )
    ).scalar_one()
    assert count == 2


async def test_ix_execution_attempts_closes_allocation_index_exists(
    conn: AsyncConnection,
) -> None:
    found = (
        await conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'execution_attempts' "
                "AND indexname = 'ix_execution_attempts_closes_allocation'"
            )
        )
    ).scalar_one_or_none()
    assert found == 1


def test_downgrade_refuses_then_forced_downgrade_and_upgrade_round_trips(
    database_url: str,
) -> None:
    """Rehearses the exact sequence the migration rehearsal procedure runs
    against a throwaway copy of the real database: a guarded downgrade
    refuses when data would be lost, the forced downgrade discards only the
    FAILED rows it names, and upgrading again restores the partial index --
    proving 0012's own precedent (never silently delete trading history)
    still holds under the relaxed constraint."""

    async def _clear_prior_test_data() -> None:
        """The downgrade guard scans the WHOLE table, not just this test's
        own rows -- and the earlier tests in this module deliberately leave
        allocations with more than one closing attempt behind (that is what
        they are testing). A FILLED+SUBMITTED pair from
        ``test_a_filled_close_does_not_block_a_residual_close`` has no
        FAILED row to force-drop, so it would make EVERY future downgrade
        in this shared throwaway database refuse forever. Clearing it here
        is exactly what the real rehearsal does with a fresh restore."""
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                # Plain DELETE, not TRUNCATE ... CASCADE: cascading into
                # ``reservations`` would reach ``ledger_entries``, which is
                # append-only and refuses TRUNCATE outright
                # (``trg_ledger_no_truncate``). None of this file's rows
                # ever produce a ledger entry, so a dependency-ordered
                # DELETE is both sufficient and safe.
                for table in ("execution_attempts", "reservations", "signals", "strategies"):
                    await connection.execute(text(f"DELETE FROM {table}"))  # noqa: S608
                await connection.commit()
        finally:
            await engine.dispose()

    async def _seed_two_closes(status_a: str, status_b: str) -> UUID:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                allocation_id = await _seed_allocation(connection)
                await _insert_close(connection, allocation_id=allocation_id, status=status_a)
                await _insert_close(connection, allocation_id=allocation_id, status=status_b)
                await connection.commit()
            return allocation_id
        finally:
            await engine.dispose()

    async def _close_count(allocation_id: UUID) -> int:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM execution_attempts "
                            "WHERE closes_allocation_id = :id"
                        ),
                        {"id": allocation_id},
                    )
                ).scalar_one()
        finally:
            await engine.dispose()

    async def _unique_constraint_exists() -> bool:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return bool(
                    (
                        await connection.execute(
                            text(
                                "SELECT 1 FROM pg_constraint WHERE conname = "
                                "'uq_execution_attempts_closes_allocation'"
                            )
                        )
                    ).scalar_one_or_none()
                )
        finally:
            await engine.dispose()

    asyncio.run(_clear_prior_test_data())
    allocation_id = asyncio.run(_seed_two_closes("FAILED", "SUBMITTED"))

    # A plain downgrade refuses -- more than one closing attempt exists on
    # this allocation, and the pre-0021 shape cannot represent that.
    refused = _run_alembic(database_url, "downgrade", "0020")
    assert refused.returncode != 0
    assert str(allocation_id) in refused.stdout + refused.stderr
    assert "2" in refused.stdout + refused.stderr

    # The forced downgrade deletes only the FAILED row, leaving the single
    # SUBMITTED one -- the full UNIQUE becomes satisfiable. ``-x`` is a
    # GLOBAL alembic option and must precede the subcommand.
    _run_alembic_ok(
        database_url, "-x", "force_failed_close_drop=1", "downgrade", "0020"
    )
    assert asyncio.run(_close_count(allocation_id)) == 1
    assert asyncio.run(_unique_constraint_exists()) is True

    _run_alembic_ok(database_url, "upgrade", "head")
    assert asyncio.run(_unique_constraint_exists()) is False

    async def _live_close_index_exists() -> bool:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return bool(
                    (
                        await connection.execute(
                            text(
                                "SELECT 1 FROM pg_indexes WHERE tablename = "
                                "'execution_attempts' AND indexname = "
                                "'ux_execution_attempts_live_close'"
                            )
                        )
                    ).scalar_one_or_none()
                )
        finally:
            await engine.dispose()

    assert asyncio.run(_live_close_index_exists()) is True

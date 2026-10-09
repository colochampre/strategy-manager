"""Migration ``0026`` -- ``reservations.pool_total_at_open`` (design.md section
10; tasks.md PR 6a, unit 3a).

An additive nullable column: no seeding and no backfill, because the value is
the pool capital as it stood when the reservation was made and cannot be
reconstructed afterwards. Most tests run against a database already migrated to
``head``, following ``test_0025_signal_outcomes.py``. The one test that
completes a downgrade needs its own throwaway database, since a real downgrade
drops a column every other test in this module depends on.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings
from tests.pg_drop import drop_database_if_exists

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_reservation_pool_total"
_THROWAWAY_DB_PREFIX = "strategy_manager_test_reservation_pool_total_throwaway"

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}
_POSITIVE_CHECK = "ck_reservations_pool_total_at_open_positive"


def _maintenance_dsn(dev_url: str) -> str:
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    return re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)


def _database_url(dev_url: str, name: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{name}\1", dev_url)


async def _create_database(maintenance_dsn: str, name: str) -> None:
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs an alembic subcommand in a subprocess so alembic's own
    ``asyncio.run`` never collides with the test's already-running loop."""

    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


def _run_alembic_ok(database_url: str, *args: str) -> None:
    result = _run_alembic(database_url, *args)
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


def _constraint_name(error: IntegrityError) -> str | None:
    """Identifies the violated constraint BY NAME, never by message text
    (binding testing rule; same helper as ``test_0025_signal_outcomes.py``)."""
    cause = error.orig.__cause__
    return getattr(cause, "constraint_name", None)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    url = _database_url(dev_url, _DB_NAME)

    asyncio.run(drop_database_if_exists(maintenance_dsn, _DB_NAME))
    asyncio.run(_create_database(maintenance_dsn, _DB_NAME))
    _run_alembic_ok(url, "upgrade", "head")

    yield url

    asyncio.run(drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _seed_strategy(conn: AsyncConnection) -> UUID:
    strategy_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, :exchange, :venue, :settlement_currency, false, 'PARTIAL')"
        ),
        {"id": strategy_id, "name": f"strategy-{strategy_id}", **_POOL},
    )
    return strategy_id


async def _seed_signal(conn: AsyncConnection, *, strategy_id: UUID) -> UUID:
    signal_id = uuid4()
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
    return signal_id


async def _insert_reservation(
    conn: AsyncConnection, *, pool_total_at_open: Decimal | None, omit_column: bool = False
) -> UUID:
    """Seeds a strategy and signal, then a reservation carrying the value.
    ``omit_column`` writes the row exactly as code from before 0026 did."""

    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    reservation_id = uuid4()
    columns = (
        "id, strategy_id, signal_id, exchange, venue, settlement_currency, "
        "amount, status, expires_at"
    )
    values = (
        ":id, :strategy_id, :signal_id, :exchange, :venue, :settlement_currency, "
        "100, 'PENDING', :expires_at"
    )
    params: dict[str, object] = {
        "id": reservation_id,
        "strategy_id": strategy_id,
        "signal_id": signal_id,
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        **_POOL,
    }
    if not omit_column:
        columns += ", pool_total_at_open"
        values += ", :pool_total_at_open"
        params["pool_total_at_open"] = pool_total_at_open
    await conn.execute(
        text(f"INSERT INTO reservations ({columns}) VALUES ({values})"),  # noqa: S608
        params,
    )
    return reservation_id


async def _stored(conn: AsyncConnection, reservation_id: UUID) -> Decimal | None:
    return (
        await conn.execute(
            text("SELECT pool_total_at_open FROM reservations WHERE id = :id"),
            {"id": reservation_id},
        )
    ).scalar_one()


# --------------------------------------------------------------------------
# 3a.1 -- column and CHECK
# --------------------------------------------------------------------------


async def test_pool_total_at_open_check_allows_null_or_positive(conn: AsyncConnection) -> None:
    null_id = await _insert_reservation(conn, pool_total_at_open=None)
    positive_id = await _insert_reservation(conn, pool_total_at_open=Decimal("500.25"))
    legacy_id = await _insert_reservation(conn, pool_total_at_open=None, omit_column=True)
    await conn.commit()

    assert await _stored(conn, null_id) is None
    assert await _stored(conn, positive_id) == Decimal("500.25")
    # A row written by pre-0026 code (column not named) stays NULL: no default.
    assert await _stored(conn, legacy_id) is None


@pytest.mark.parametrize("refused", [Decimal("0"), Decimal("-1"), Decimal("-0.000000000000000001")])
async def test_pool_total_at_open_check_refuses_zero_and_negative(
    conn: AsyncConnection, refused: Decimal
) -> None:
    with pytest.raises(IntegrityError) as exc_info:
        await _insert_reservation(conn, pool_total_at_open=refused)
    assert _constraint_name(exc_info.value) == _POSITIVE_CHECK
    await conn.rollback()


# --------------------------------------------------------------------------
# 3a.1 -- downgrade refuses while any non-null value exists, naming the count
# --------------------------------------------------------------------------


async def test_downgrade_refuses_while_any_non_null_value_exists(
    conn: AsyncConnection, database_url: str
) -> None:
    await _insert_reservation(conn, pool_total_at_open=Decimal("750"))
    await conn.commit()
    non_null = (
        await conn.execute(
            text("SELECT count(*) FROM reservations WHERE pool_total_at_open IS NOT NULL")
        )
    ).scalar_one()
    assert non_null >= 1

    refused = _run_alembic(database_url, "downgrade", "0025")

    assert refused.returncode != 0
    output = refused.stdout + refused.stderr
    assert f"{non_null} reservations row(s)" in output
    assert "no force flag" in output
    # The refusal left the column in place: nothing was dropped.
    still_there = (
        await conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'reservations' AND column_name = 'pool_total_at_open'"
            )
        )
    ).scalar_one()
    assert still_there == 1


# --------------------------------------------------------------------------
# Downgrade actually succeeds while every value is NULL -- its own throwaway
# DB, since a completed downgrade drops a column the tests above depend on.
# --------------------------------------------------------------------------


@pytest.fixture
def throwaway_db_factory() -> Iterator[Callable[[str], str]]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    created: list[str] = []

    def make(suffix: str) -> str:
        name = f"{_THROWAWAY_DB_PREFIX}_{suffix}"
        url = _database_url(dev_url, name)
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))
        asyncio.run(_create_database(maintenance_dsn, name))
        _run_alembic_ok(url, "upgrade", "head")
        created.append(name)
        return url

    yield make

    for name in created:
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))


def test_downgrade_succeeds_while_every_value_is_null_and_drops_the_column(
    throwaway_db_factory: Callable[[str], str],
) -> None:
    url = throwaway_db_factory("clean")

    async def seed_null_row() -> None:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                # A pre-0026-style row with a NULL value must not block the downgrade.
                await _insert_reservation(connection, pool_total_at_open=None)
                await connection.commit()
        finally:
            await engine.dispose()

    async def column_count() -> int:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM information_schema.columns "
                            "WHERE table_name = 'reservations' "
                            "AND column_name = 'pool_total_at_open'"
                        )
                    )
                ).scalar_one()
        finally:
            await engine.dispose()

    asyncio.run(seed_null_row())
    assert asyncio.run(column_count()) == 1

    result = _run_alembic(url, "downgrade", "0025")

    assert result.returncode == 0, result.stdout + result.stderr
    assert asyncio.run(column_count()) == 0

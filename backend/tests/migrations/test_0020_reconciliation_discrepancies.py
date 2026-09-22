"""Tier B: migration ``0020`` — ``reconciliation_discrepancies`` (design.md §
SQL Schema and Migration Map; spec: reconcile-venue-fills).

Runs against a real ``alembic upgrade head`` database (the only way to
exercise a generated column, a partial unique index and a composite FK's
``ON DELETE`` behaviour — ``Base.metadata.create_all`` and SQLite-style
fixtures know none of it), following the same pattern as
``tests/ledger/infrastructure/test_append_only_guard.py``. The database is
dropped at teardown.

Every test reuses the ``(pionex, spot, USDT)`` pool migration ``0003``
already seeds and migration ``0017``/``0018`` already backfilled — no
additional pool needs inserting.

``kind`` carries the four verdicts of the classification ladder, and
``status`` the two states a row moves through. This test only needs a CHECK
that accepts one member and rejects a value outside it; the ladder's own
precedence is a domain rule, exercised in the classification tests, not here.
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
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_reconciliation"

# One of the four verdicts the CHECK accepts. Any of them works for these
# tests; this one reads naturally in the "venue moved without the ledger"
# scenarios below.
_ACCEPTED_KIND = "ATTRIBUTABLE_SINGLE_ALLOCATION"
_REJECTED_KIND = "NOT_A_REAL_VERDICT"

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


def _run_alembic(database_url: str, *args: str) -> None:
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
    _run_alembic(url, "upgrade", "head")

    yield url

    asyncio.run(_drop_database_if_exists(maintenance_dsn, _DB_NAME))


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _insert_discrepancy(
    conn: AsyncConnection,
    *,
    symbol: str = "BTCUSDT",
    kind: str = _ACCEPTED_KIND,
    venue_net_base: Decimal = Decimal("1.5"),
    ledger_net_base: Decimal = Decimal("1.0"),
    consecutive_scans: int = 1,
    status: str = "OBSERVED",
    confirmed_at_sql: str = "NULL",
    resolved_at_sql: str = "NULL",
) -> object:
    row_id = uuid4()
    # first_scan_id/last_scan_id are jobs.id values and carry no FK, so a bare
    # UUID is a faithful stand-in here — the migration only requires them present.
    scan_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO reconciliation_discrepancies "
            "(id, exchange, venue, settlement_currency, symbol, kind, "
            "venue_net_base, ledger_net_base, consecutive_scans, status, "
            "first_scan_id, last_scan_id, "
            f"confirmed_at, resolved_at) "
            "VALUES (:id, :exchange, :venue, :settlement_currency, :symbol, :kind, "
            f":venue_net_base, :ledger_net_base, :consecutive_scans, :status, "
            f":scan_id, :scan_id, "
            f"{confirmed_at_sql}, {resolved_at_sql})"
        ),
        {
            "id": row_id,
            "scan_id": scan_id,
            "exchange": _POOL["exchange"],
            "venue": _POOL["venue"],
            "settlement_currency": _POOL["settlement_currency"],
            "symbol": symbol,
            "kind": kind,
            "venue_net_base": venue_net_base,
            "ledger_net_base": ledger_net_base,
            "consecutive_scans": consecutive_scans,
            "status": status,
        },
    )
    return row_id


async def test_delta_base_is_generated_from_venue_minus_ledger(
    conn: AsyncConnection,
) -> None:
    row_id = await _insert_discrepancy(
        conn, venue_net_base=Decimal("1.5"), ledger_net_base=Decimal("1.0")
    )
    await conn.commit()

    delta = (
        await conn.execute(
            text("SELECT delta_base FROM reconciliation_discrepancies WHERE id = :id"),
            {"id": row_id},
        )
    ).scalar_one()
    assert delta == Decimal("0.5")


async def test_open_allocation_ids_defaults_to_empty_and_round_trips(
    conn: AsyncConnection,
) -> None:
    """Slice 2 acts on a CONFIRMED row's stored allocations rather than
    re-deriving them, so the column has to survive a write unchanged — and a
    NO_MATCHING_ALLOCATION verdict has to be able to carry none at all."""

    row_id = await _insert_discrepancy(
        conn, symbol="AVAXUSDT", kind="NO_MATCHING_ALLOCATION"
    )
    await conn.commit()

    async def stored() -> list[object]:
        result = await conn.execute(
            text(
                "SELECT open_allocation_ids FROM reconciliation_discrepancies "
                "WHERE id = :id"
            ),
            {"id": row_id},
        )
        return list(result.scalar_one())

    assert await stored() == []

    allocations = [uuid4(), uuid4()]
    await conn.execute(
        text(
            "UPDATE reconciliation_discrepancies SET open_allocation_ids = :ids "
            "WHERE id = :id"
        ),
        {"ids": allocations, "id": row_id},
    )
    await conn.commit()

    assert await stored() == allocations


async def test_second_open_row_for_same_pool_and_symbol_is_refused(
    conn: AsyncConnection,
) -> None:
    await _insert_discrepancy(conn, symbol="ETHUSDT")
    await conn.commit()

    with pytest.raises(IntegrityError):
        await _insert_discrepancy(conn, symbol="ETHUSDT")
    await conn.rollback()


async def test_a_resolved_row_does_not_block_a_new_open_one_for_the_same_symbol(
    conn: AsyncConnection,
) -> None:
    await _insert_discrepancy(conn, symbol="SOLUSDT", resolved_at_sql="now()")
    # The first row is already resolved (resolved_at IS NOT NULL), so the
    # partial unique index does not apply to it — a fresh open row for the
    # same pool+symbol must be allowed.
    await _insert_discrepancy(conn, symbol="SOLUSDT")
    await conn.commit()

    count = (
        await conn.execute(
            text(
                "SELECT COUNT(*) FROM reconciliation_discrepancies "
                "WHERE symbol = 'SOLUSDT'"
            )
        )
    ).scalar_one()
    assert count == 2


async def test_deleting_a_pool_that_carries_a_discrepancy_is_refused(
    conn: AsyncConnection,
) -> None:
    await _insert_discrepancy(conn, symbol="XRPUSDT")
    await conn.commit()

    with pytest.raises(DBAPIError) as exc_info:
        await conn.execute(
            text(
                "DELETE FROM capital_pools WHERE exchange = :exchange "
                "AND venue = :venue AND settlement_currency = :settlement_currency"
            ),
            _POOL,
        )
    assert getattr(exc_info.value.orig, "sqlstate", None) == "23503"  # foreign_key_violation
    await conn.rollback()

    still_there = (
        await conn.execute(
            text(
                "SELECT 1 FROM capital_pools WHERE exchange = :exchange "
                "AND venue = :venue AND settlement_currency = :settlement_currency"
            ),
            _POOL,
        )
    ).scalar_one_or_none()
    assert still_there == 1


async def test_confirmed_status_requires_confirmed_at(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError):
        await _insert_discrepancy(conn, symbol="ADAUSDT", status="CONFIRMED")
    await conn.rollback()

    # The matching pair is accepted.
    await _insert_discrepancy(
        conn, symbol="ADAUSDT", status="CONFIRMED", confirmed_at_sql="now()"
    )
    await conn.commit()


async def test_a_demoted_row_keeps_the_timestamp_of_the_confirmation_it_earned(
    conn: AsyncConnection,
) -> None:
    """The CHECK is a one-way implication, not an equivalence.

    consecutive_scans resets to 1 whenever an observation moves, demoting a
    previously CONFIRMED row back to OBSERVED. An equivalence CHECK would
    force the repository to erase confirmed_at on that demotion, destroying
    the record that the disagreement once held still long enough to be
    confirmed -- every time it wobbled. So OBSERVED with a confirmed_at is
    legal, and it means "was first confirmed then, and has moved since".
    """
    await _insert_discrepancy(
        conn, symbol="LINKUSDT", status="OBSERVED", confirmed_at_sql="now()"
    )
    await conn.commit()

    status, confirmed_at = (
        await conn.execute(
            text(
                "SELECT status, confirmed_at FROM reconciliation_discrepancies "
                "WHERE symbol = 'LINKUSDT'"
            )
        )
    ).one()
    assert status == "OBSERVED"
    assert confirmed_at is not None


async def test_consecutive_scans_must_be_at_least_one(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError):
        await _insert_discrepancy(conn, symbol="DOTUSDT", consecutive_scans=0)
    await conn.rollback()

    await _insert_discrepancy(conn, symbol="DOTUSDT", consecutive_scans=1)
    await conn.commit()


async def test_kind_check_rejects_a_value_outside_the_accepted_set(
    conn: AsyncConnection,
) -> None:
    with pytest.raises(IntegrityError):
        await _insert_discrepancy(conn, symbol="LTCUSDT", kind=_REJECTED_KIND)
    await conn.rollback()

    await _insert_discrepancy(conn, symbol="LTCUSDT", kind=_ACCEPTED_KIND)
    await conn.commit()


async def test_ix_ledger_pool_symbol_index_exists_on_ledger_entries(
    conn: AsyncConnection,
) -> None:
    found = (
        await conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'ledger_entries' "
                "AND indexname = 'ix_ledger_pool_symbol'"
            )
        )
    ).scalar_one_or_none()
    assert found == 1


def test_downgrade_then_upgrade_round_trips(database_url: str) -> None:
    """Rehearses the exact sequence the migration rehearsal procedure runs
    against a throwaway copy of the real database: up, down, up again.

    Targets the explicit revision ``0019`` (0020's own ``down_revision``)
    rather than the relative ``-1``, which would undo whatever migration is
    head AT THE TIME this runs, not necessarily 0020 -- exactly the trap a
    later migration (``0021``) fell into when it was added on top."""

    _run_alembic(database_url, "downgrade", "0019")

    async def _table_exists() -> bool:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                return bool(
                    (
                        await connection.execute(
                            text(
                                "SELECT 1 FROM information_schema.tables "
                                "WHERE table_name = 'reconciliation_discrepancies'"
                            )
                        )
                    ).scalar_one_or_none()
                )
        finally:
            await engine.dispose()

    assert asyncio.run(_table_exists()) is False

    _run_alembic(database_url, "upgrade", "head")
    assert asyncio.run(_table_exists()) is True

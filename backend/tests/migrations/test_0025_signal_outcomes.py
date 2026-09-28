"""Migration ``0025`` -- ``signals.outcome_reason``/``outcome_detail``/
``decided_at`` and ``execution_attempts.signal_id`` (decision 25,
owner-decisions.md 25-26; design.md "Addendum: signal outcomes (decision
25)" § D; tasks.md PR 5b, task 5b.2).

No seeding or backfill: both changes are additive and nullable, and every
signal ingested before this migration stays ``ACCEPTED`` (nothing is
reconstructed). Most tests run against a database already migrated to
``head``, following ``test_0024_strategy_lifecycle.py``'s own pattern
(itself following ``0021``/``0022``). The one test that actually completes a
downgrade (rather than only proving it refuses) needs its own throwaway
database, since a real downgrade drops columns every other test in this
module depends on.
"""

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_signal_outcomes"
_THROWAWAY_DB_PREFIX = "strategy_manager_test_signal_outcomes_throwaway"

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}

_REJECTED_REQUIRES_REASON_CHECK = "ck_signals_rejected_requires_outcome_reason"
_TERMINAL_REQUIRES_DECIDED_AT_CHECK = "ck_signals_terminal_requires_decided_at"
_SIGNAL_ID_FK = "fk_execution_attempts_signal"


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
    """Same helper as ``test_0024_strategy_lifecycle.py``/
    ``test_0023_booking_proposals.py``: the asyncpg driver's own
    ``PostgresError`` (which carries ``constraint_name`` directly) sits as
    ``__cause__`` of SQLAlchemy's DBAPI wrapper. Identifies the violated
    constraint BY NAME, never by message text (binding testing rule)."""
    cause = error.orig.__cause__
    return getattr(cause, "constraint_name", None)


# --------------------------------------------------------------------------
# Fixtures: a shared database already migrated to head, for CHECK/FK and
# downgrade-refusal tests (the refusal never actually completes the
# downgrade, so the shared database stays intact for later tests).
# --------------------------------------------------------------------------


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


async def _seed_reservation(
    conn: AsyncConnection, *, strategy_id: UUID, signal_id: UUID
) -> UUID:
    reservation_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO reservations "
            "(id, strategy_id, signal_id, exchange, venue, settlement_currency, amount, "
            "status, expires_at) "
            "VALUES (:id, :strategy_id, :signal_id, :exchange, :venue, :settlement_currency, "
            "100, 'SUBMITTED', :expires_at)"
        ),
        {
            "id": reservation_id,
            "strategy_id": strategy_id,
            "signal_id": signal_id,
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
            **_POOL,
        },
    )
    return reservation_id


async def _seed_execution_attempt(
    conn: AsyncConnection, *, reservation_id: UUID, signal_id: UUID | None
) -> UUID:
    attempt_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution_attempts "
            "(id, reservation_id, signal_id, exchange, venue, settlement_currency, symbol, "
            "side, quantity, status, client_order_id) "
            "VALUES (:id, :reservation_id, :signal_id, :exchange, :venue, "
            ":settlement_currency, 'BTCUSDT', 'BUY', 1, 'SUBMITTED', :client_order_id)"
        ),
        {
            "id": attempt_id,
            "reservation_id": reservation_id,
            "signal_id": signal_id,
            "client_order_id": f"client-{attempt_id}",
            **_POOL,
        },
    )
    return attempt_id


# --------------------------------------------------------------------------
# 5b.2 -- columns and CHECK constraints
# --------------------------------------------------------------------------


async def test_accepted_signal_needs_neither_outcome_reason_nor_decided_at(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    await _seed_signal(conn, strategy_id=strategy_id)
    # No exception -- both CHECKs are satisfied by the default ACCEPTED status
    # with null outcome_reason/decided_at.
    await conn.commit()


async def test_processing_does_not_require_outcome_fields(conn: AsyncConnection) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    await conn.commit()

    await conn.execute(
        text("UPDATE signals SET status = 'PROCESSING' WHERE id = :id"), {"id": signal_id}
    )
    await conn.commit()


async def test_rejected_without_outcome_reason_violates_check_constraint(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    await conn.commit()

    with pytest.raises(IntegrityError) as exc_info:
        await conn.execute(
            text(
                "UPDATE signals SET status = 'REJECTED', decided_at = now() WHERE id = :id"
            ),
            {"id": signal_id},
        )
    assert _constraint_name(exc_info.value) == _REJECTED_REQUIRES_REASON_CHECK
    await conn.rollback()


async def test_rejected_without_decided_at_violates_terminal_check_constraint(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    await conn.commit()

    with pytest.raises(IntegrityError) as exc_info:
        await conn.execute(
            text(
                "UPDATE signals SET status = 'REJECTED', outcome_reason = 'UNTRADABLE_POOL' "
                "WHERE id = :id"
            ),
            {"id": signal_id},
        )
    assert _constraint_name(exc_info.value) == _TERMINAL_REQUIRES_DECIDED_AT_CHECK
    await conn.rollback()


async def test_processed_without_decided_at_violates_terminal_check_constraint(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    await conn.commit()

    with pytest.raises(IntegrityError) as exc_info:
        await conn.execute(
            text("UPDATE signals SET status = 'PROCESSED' WHERE id = :id"), {"id": signal_id}
        )
    assert _constraint_name(exc_info.value) == _TERMINAL_REQUIRES_DECIDED_AT_CHECK
    await conn.rollback()


async def test_rejected_with_reason_and_decided_at_succeeds(conn: AsyncConnection) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    await conn.commit()

    await conn.execute(
        text(
            "UPDATE signals SET status = 'REJECTED', outcome_reason = 'UNTRADABLE_POOL', "
            "outcome_detail = 'no key stored', decided_at = now() WHERE id = :id"
        ),
        {"id": signal_id},
    )
    await conn.commit()


# --------------------------------------------------------------------------
# 5b.2 -- execution_attempts.signal_id, FK
# --------------------------------------------------------------------------


async def test_execution_attempt_signal_id_fk_refuses_unknown_signal(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    reservation_id = await _seed_reservation(conn, strategy_id=strategy_id, signal_id=signal_id)
    await conn.commit()

    with pytest.raises(IntegrityError) as exc_info:
        await _seed_execution_attempt(
            conn, reservation_id=reservation_id, signal_id=uuid4()
        )
    assert _constraint_name(exc_info.value) == _SIGNAL_ID_FK
    await conn.rollback()


async def test_execution_attempt_signal_id_accepts_a_real_signal_and_defaults_null(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    other_signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    reservation_id = await _seed_reservation(conn, strategy_id=strategy_id, signal_id=signal_id)
    other_reservation_id = await _seed_reservation(
        conn, strategy_id=strategy_id, signal_id=other_signal_id
    )
    await conn.commit()

    # ``reservation_id`` is unconditionally UNIQUE (migration 0012): each
    # attempt needs its OWN reservation, not two attempts on one.
    linked_id = await _seed_execution_attempt(
        conn, reservation_id=reservation_id, signal_id=signal_id
    )
    unlinked_id = await _seed_execution_attempt(
        conn, reservation_id=other_reservation_id, signal_id=None
    )
    await conn.commit()

    rows = (
        await conn.execute(
            text("SELECT id, signal_id FROM execution_attempts WHERE id = ANY(:ids)"),
            {"ids": [linked_id, unlinked_id]},
        )
    ).mappings().all()
    by_id = {row["id"]: row["signal_id"] for row in rows}
    assert by_id[linked_id] == signal_id
    assert by_id[unlinked_id] is None


# --------------------------------------------------------------------------
# 5b.2 -- downgrade refuses while outcomes exist, naming both counts
# --------------------------------------------------------------------------


async def test_downgrade_refuses_while_any_signal_is_not_accepted_naming_count(
    conn: AsyncConnection, database_url: str
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    await conn.commit()
    await conn.execute(
        text(
            "UPDATE signals SET status = 'REJECTED', outcome_reason = 'UNTRADABLE_POOL', "
            "decided_at = now() WHERE id = :id"
        ),
        {"id": signal_id},
    )
    await conn.commit()

    refused = _run_alembic(database_url, "downgrade", "0024")
    assert refused.returncode != 0
    output = refused.stdout + refused.stderr
    assert "1" in output
    assert "ACCEPTED" in output


async def test_downgrade_refuses_while_any_execution_attempt_carries_signal_id_naming_count(
    conn: AsyncConnection, database_url: str
) -> None:
    strategy_id = await _seed_strategy(conn)
    signal_id = await _seed_signal(conn, strategy_id=strategy_id)
    reservation_id = await _seed_reservation(conn, strategy_id=strategy_id, signal_id=signal_id)
    await conn.commit()
    await _seed_execution_attempt(conn, reservation_id=reservation_id, signal_id=signal_id)
    await conn.commit()

    refused = _run_alembic(database_url, "downgrade", "0024")
    assert refused.returncode != 0
    output = refused.stdout + refused.stderr
    assert "1" in output
    assert "execution_attempts" in output


# --------------------------------------------------------------------------
# Downgrade actually succeeds on a clean database -- its own throwaway DB,
# since a completed downgrade drops columns every test above depends on.
# --------------------------------------------------------------------------


@pytest.fixture
def throwaway_db_factory() -> Iterator[Callable[[str], str]]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    created: list[str] = []

    def make(suffix: str) -> str:
        name = f"{_THROWAWAY_DB_PREFIX}_{suffix}"
        url = _database_url(dev_url, name)
        asyncio.run(_drop_database_if_exists(maintenance_dsn, name))
        asyncio.run(_create_database(maintenance_dsn, name))
        _run_alembic_ok(url, "upgrade", "head")
        created.append(name)
        return url

    yield make

    for name in created:
        asyncio.run(_drop_database_if_exists(maintenance_dsn, name))


def test_downgrade_succeeds_on_a_clean_database(
    throwaway_db_factory: Callable[[str], str],
) -> None:
    url = throwaway_db_factory("clean")

    result = _run_alembic(url, "downgrade", "0024")
    assert result.returncode == 0, result.stdout + result.stderr

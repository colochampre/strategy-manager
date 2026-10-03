"""Migration ``0028`` -- enablement events are deleted with their strategy
(design addendum 9x, § G; owner decision 42, Q1; tasks.md 9xf).

Real PostgreSQL, on databases ``tests/pg_head_schema.py`` migrates to ``head``. Two
kinds of database:

- one module-scoped database. Every test seeds ids of its own and asserts only on
  them, because the events table is append-only and cannot be emptied between tests;
- throwaway databases, for the tests that complete a downgrade, run a ``TRUNCATE``,
  or move the schema back and forth.

The first test is the design's ASSUMPTION: while PostgreSQL runs the foreign
key's cascade, the append-only trigger must no longer see the parent row, so a
``NOT EXISTS`` condition on it lets the cascaded delete through and nothing else.

Rule 1: no real credential and no venue call.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_head_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_events_cascade"
_THROWAWAY_DB_PREFIX = "strategy_manager_test_events_cascade_throwaway"

_EVENTS = "strategy_enablement_events"
_EVENTS_FK = "fk_strategy_enablement_events_strategy"
_FUNCTION = "fn_strategy_enablement_events_append_only"
_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}

# ``alembic.ini`` formats levels as ``%(levelname)-5.5s``: WARNING prints as
# "WARNI". Asserting the truncated label is what proves WARNING and not INFO.
_WARNING_LEVEL_LABEL = "WARNI"

_ON_DELETE_NO_ACTION = "a"
_ON_DELETE_CASCADE = "c"


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with the test's running loop."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


def _run_alembic_ok(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = _run_alembic(database_url, *args)
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result


def _constraint_name(error: IntegrityError) -> str | None:
    """The violated constraint BY NAME, never by message text."""
    return getattr(error.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _sqlstate(error: DBAPIError) -> str | None:
    """The SQLSTATE of the driver error: ``23001`` is ``restrict_violation``, what
    the append-only trigger raises."""
    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with migrated_head_database(_DB_NAME) as url:
        yield url


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


@pytest.fixture
def throwaway_db_factory() -> Iterator[Callable[[str], str]]:
    """``make(suffix)`` -> a fresh database migrated to ``head``, dropped afterwards."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_head_database(f"{_THROWAWAY_DB_PREFIX}_{suffix}")
        )


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------


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


async def _seed_event(conn: AsyncConnection, strategy_id: UUID, *, enabled: bool = True) -> UUID:
    event_id = uuid4()
    await conn.execute(
        text(
            f"INSERT INTO {_EVENTS} (id, strategy_id, enabled, origin) "  # noqa: S608
            "VALUES (:id, :strategy_id, :enabled, 'OBSERVED')"
        ),
        {"id": event_id, "strategy_id": strategy_id, "enabled": enabled},
    )
    return event_id


async def _seed_signal(conn: AsyncConnection, strategy_id: UUID) -> UUID:
    signal_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) "
            "VALUES (:id, :strategy_id, :key, '{}'::jsonb, 'buy', 1, 1, 1, 'STXUSDT.P', "
            ":signal_type)"
        ),
        {
            "id": signal_id,
            "strategy_id": strategy_id,
            "key": f"key-{signal_id}",
            "signal_type": str(strategy_id),
        },
    )
    return signal_id


async def _delete_strategy(conn: AsyncConnection, strategy_id: UUID) -> str | None:
    """Delete a strategy and return the name of the constraint that refused it, or
    ``None`` when it was deleted. A savepoint keeps the outer transaction usable,
    and returning the name makes a wrong outcome an assertion, not an exception."""
    try:
        async with conn.begin_nested():
            await conn.execute(text("DELETE FROM strategies WHERE id = :id"), {"id": strategy_id})
    except IntegrityError as error:
        return _constraint_name(error)
    return None


async def _count(conn: AsyncConnection, sql: str, **params: object) -> int:
    value = await conn.scalar(text(sql), params)
    assert isinstance(value, int)
    return value


async def _events_of(conn: AsyncConnection, strategy_id: UUID) -> int:
    return await _count(
        conn,
        f"SELECT count(*) FROM {_EVENTS} WHERE strategy_id = :id",  # noqa: S608
        id=strategy_id,
    )


async def _strategies_with(conn: AsyncConnection, strategy_id: UUID) -> int:
    return await _count(conn, "SELECT count(*) FROM strategies WHERE id = :id", id=strategy_id)


async def _foreign_key_on_delete(conn: AsyncConnection) -> str | None:
    return await conn.scalar(
        text("SELECT confdeltype::text FROM pg_constraint WHERE conname = :name"),
        {"name": _EVENTS_FK},
    )


async def _function_source(conn: AsyncConnection) -> str:
    source = await conn.scalar(
        text("SELECT prosrc FROM pg_proc WHERE proname = :name"), {"name": _FUNCTION}
    )
    assert isinstance(source, str)
    return source


def _on_throwaway(url: str, work: Callable[[AsyncConnection], object]) -> object:
    """Run ``work`` once on a fresh connection to ``url`` and commit."""

    async def run() -> object:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.begin() as connection:
                return await work(connection)  # type: ignore[misc]
        finally:
            await engine.dispose()

    return asyncio.run(run())


# --------------------------------------------------------------------------
# 9xf.1 -- the behaviour at head
# --------------------------------------------------------------------------


async def test_deleting_a_strategy_takes_its_enablement_events_with_it(
    conn: AsyncConnection,
) -> None:
    """The design's assumption: inside the cascade the trigger no longer sees the
    parent row, so the cascaded delete passes the ``NOT EXISTS`` condition."""
    strategy_id = await _seed_strategy(conn)
    await _seed_event(conn, strategy_id, enabled=True)
    await _seed_event(conn, strategy_id, enabled=False)
    await conn.commit()
    assert await _events_of(conn, strategy_id) == 2

    refused_by = await _delete_strategy(conn, strategy_id)
    await conn.commit()

    assert refused_by is None
    assert await _strategies_with(conn, strategy_id) == 0
    assert await _events_of(conn, strategy_id) == 0


async def test_a_cascade_takes_only_the_deleted_strategys_events(
    conn: AsyncConnection,
) -> None:
    gone = await _seed_strategy(conn)
    kept = await _seed_strategy(conn)
    await _seed_event(conn, gone)
    await _seed_event(conn, kept)
    await conn.commit()

    refused_by = await _delete_strategy(conn, gone)
    await conn.commit()

    assert refused_by is None
    assert await _events_of(conn, gone) == 0
    assert await _events_of(conn, kept) == 1


async def test_a_direct_delete_of_an_event_whose_strategy_exists_is_still_refused(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn)
    event_id = await _seed_event(conn, strategy_id)
    await conn.commit()

    with pytest.raises(DBAPIError, match="(?i)append-only") as raised:
        await conn.execute(text(f"DELETE FROM {_EVENTS} WHERE id = :id"), {"id": event_id})  # noqa: S608
    await conn.rollback()

    assert _sqlstate(raised.value) == "23001"  # restrict_violation
    assert await _events_of(conn, strategy_id) == 1
    assert await _strategies_with(conn, strategy_id) == 1


async def test_an_update_of_an_event_is_still_refused(conn: AsyncConnection) -> None:
    strategy_id = await _seed_strategy(conn)
    event_id = await _seed_event(conn, strategy_id, enabled=True)
    await conn.commit()

    with pytest.raises(DBAPIError, match="(?i)append-only") as raised:
        await conn.execute(
            text(f"UPDATE {_EVENTS} SET enabled = false WHERE id = :id"),  # noqa: S608
            {"id": event_id},
        )
    await conn.rollback()

    assert _sqlstate(raised.value) == "23001"
    still_enabled = await conn.scalar(
        text(f"SELECT enabled FROM {_EVENTS} WHERE id = :id"),  # noqa: S608
        {"id": event_id},
    )
    assert still_enabled is True


async def test_a_strategy_with_a_signal_is_still_refused_and_its_events_survive(
    conn: AsyncConnection,
) -> None:
    """The cascade must not reach an event through a delete the other foreign keys
    refuse: PostgreSQL checks ``NO ACTION`` keys at the end of the statement, and
    the whole statement, cascade included, is undone."""
    strategy_id = await _seed_strategy(conn)
    await _seed_event(conn, strategy_id)
    await _seed_event(conn, strategy_id, enabled=False)
    await _seed_signal(conn, strategy_id)
    await conn.commit()

    refused_by = await _delete_strategy(conn, strategy_id)
    await conn.rollback()

    assert refused_by == "fk_signals_strategy"
    assert await _strategies_with(conn, strategy_id) == 1
    assert await _events_of(conn, strategy_id) == 2


async def test_the_foreign_key_cascades_and_the_trigger_is_conditional_at_head(
    conn: AsyncConnection,
) -> None:
    assert await _foreign_key_on_delete(conn) == _ON_DELETE_CASCADE
    assert "NOT EXISTS" in await _function_source(conn)


def test_truncate_strategies_cascade_still_works(
    throwaway_db_factory: Callable[[str], str],
) -> None:
    """The integration conftests ``TRUNCATE strategies ... CASCADE``. The events
    table has no TRUNCATE guard, on purpose (migration 0024), and the foreign
    key's new ``ON DELETE`` action does not change what TRUNCATE does.

    ``head`` also carries the ledger's own ``trg_ledger_no_truncate``, which the
    ORM-built conftest schemas do not have and which refuses any cascade that
    reaches ``ledger_entries``. It is dropped from this throwaway database only,
    so the statement is the conftests' statement."""
    url = throwaway_db_factory("truncate")

    async def work(connection: AsyncConnection) -> tuple[int, int]:
        strategy_id = await _seed_strategy(connection)
        await _seed_event(connection, strategy_id)
        await _seed_signal(connection, strategy_id)
        await connection.execute(text("DROP TRIGGER trg_ledger_no_truncate ON ledger_entries"))
        await connection.execute(text("TRUNCATE strategies CASCADE"))
        strategies = await _count(connection, "SELECT count(*) FROM strategies")
        events = await _count(connection, f"SELECT count(*) FROM {_EVENTS}")  # noqa: S608
        return strategies, events

    assert _on_throwaway(url, work) == (0, 0)


# --------------------------------------------------------------------------
# 9xf.1 -- the downgrade, the round trip and the data
# --------------------------------------------------------------------------


def test_downgrade_restores_no_action_and_the_unconditional_trigger(
    throwaway_db_factory: Callable[[str], str],
) -> None:
    url = throwaway_db_factory("downgrade")
    seeded: dict[str, UUID] = {}

    async def seed(connection: AsyncConnection) -> None:
        strategy_id = await _seed_strategy(connection)
        await _seed_event(connection, strategy_id)
        seeded["strategy"] = strategy_id

    _on_throwaway(url, seed)

    result = _run_alembic_ok(url, "downgrade", "0027")

    output = result.stdout + result.stderr
    assert output.count(_WARNING_LEVEL_LABEL) == 1  # exactly one WARNING
    assert "0028" in output
    assert "not restored" in output  # strategies deleted meanwhile stay deleted

    async def inspect(connection: AsyncConnection) -> tuple[str | None, str, str | None, int]:
        on_delete = await _foreign_key_on_delete(connection)
        source = await _function_source(connection)
        refused = await _delete_strategy(connection, seeded["strategy"])
        survivors = await _events_of(connection, seeded["strategy"])
        return on_delete, source, refused, survivors

    on_delete, source, refused, survivors = _on_throwaway(url, inspect)  # type: ignore[misc]
    assert on_delete == _ON_DELETE_NO_ACTION
    assert "NOT EXISTS" not in source  # the unconditional body of 0024
    assert refused == _EVENTS_FK  # the strategy's delete is refused again
    assert survivors == 1  # the downgrade discarded nothing


def test_upgrade_downgrade_upgrade_is_clean(
    throwaway_db_factory: Callable[[str], str],
) -> None:
    url = throwaway_db_factory("roundtrip")
    _run_alembic_ok(url, "downgrade", "0027")
    _run_alembic_ok(url, "upgrade", "head")

    async def work(connection: AsyncConnection) -> tuple[str | None, str | None, int, int]:
        strategy_id = await _seed_strategy(connection)
        await _seed_event(connection, strategy_id)
        refused_by = await _delete_strategy(connection, strategy_id)
        return (
            await _foreign_key_on_delete(connection),
            refused_by,
            await _events_of(connection, strategy_id),
            await _strategies_with(connection, strategy_id),
        )

    assert _on_throwaway(url, work) == (_ON_DELETE_CASCADE, None, 0, 0)


def test_the_migration_moves_no_row(
    throwaway_db_factory: Callable[[str], str],
) -> None:
    """Applying 0028 and reverting it change a function and a constraint, never
    data: every row of the three tables is the same at head, at 0027 and at head
    again."""
    url = throwaway_db_factory("norows")
    snapshot_sql = (
        f"SELECT (SELECT coalesce(string_agg(to_jsonb(e)::text, '|' ORDER BY e.id), '') "  # noqa: S608
        f"FROM {_EVENTS} e), "
        "(SELECT coalesce(string_agg(to_jsonb(s)::text, '|' ORDER BY s.id), '') "
        "FROM strategies s), "
        "(SELECT coalesce(string_agg(to_jsonb(g)::text, '|' ORDER BY g.id), '') FROM signals g)"
    )

    async def seed(connection: AsyncConnection) -> None:
        for _ in range(2):
            strategy_id = await _seed_strategy(connection)
            await _seed_event(connection, strategy_id)
            await _seed_event(connection, strategy_id, enabled=False)
        await _seed_signal(connection, strategy_id)

    async def snapshot(connection: AsyncConnection) -> tuple[str, ...]:
        row = (await connection.execute(text(snapshot_sql))).one()
        return tuple(row)

    _on_throwaway(url, seed)
    at_head = _on_throwaway(url, snapshot)
    assert at_head[0] and at_head[1] and at_head[2]  # the snapshot is not vacuously empty

    _run_alembic_ok(url, "downgrade", "0027")
    at_0027 = _on_throwaway(url, snapshot)
    _run_alembic_ok(url, "upgrade", "head")

    assert at_0027 == at_head
    assert _on_throwaway(url, snapshot) == at_head

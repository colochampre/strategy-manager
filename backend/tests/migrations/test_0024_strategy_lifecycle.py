"""Migration ``0024`` -- ``strategies.allowed_pairs``, ``strategies.archived_at``
and ``strategy_enablement_events`` (design.md § 6 "Allowed pairs: an array
column, migration 0024", § 9 "Enablement event log and uptime"; spec:
strategy-lifecycle § "Allowed-Pairs List Per Strategy", "Existing Strategies'
Allowed Pairs Are Seeded Once From History", "Archive Requires Disabled and
Flat", "Enable/Disable Event Log"; tasks.md Unit 2a).

Two DB shapes are exercised here, for two different reasons:

- Most tests (the CHECK constraints, the events table, the triggers, the
  downgrade refusal) run against a database already migrated to ``head``,
  following the exact pattern of
  ``tests/migrations/test_0021_execution_attempts_live_close.py`` and
  ``tests/migrations/test_0022_execution_attempt_origin.py``.
- The SEEDING tests (2a.3, 2a.4, 2a.7, and the two orchestrator-required
  tests below) need strategies/signals rows to EXIST BEFORE 0024 runs, since
  seeding reads history that predates the migration. For those,
  ``pre_migration_db_factory`` migrates a dedicated throwaway database to
  ``0023`` only, lets the test insert its own pre-migration rows, and then
  runs ``alembic upgrade head`` itself -- capturing its stdout/stderr so the
  seeding WARNING can be asserted from the *real* ``alembic upgrade``
  output, not from a mocked logger (orchestrator addition point 3).

Two tests need no database at all: the frozen-copy import-boundary check
(2a.5) reads the migration's own source text, and the frozen-copy/
``market_key()`` parity test loads the migration module directly via
``importlib`` to call its private normalizer.
"""

import asyncio
import importlib.util
import os
import re
import subprocess
import sys
import types
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.shared.config import get_settings
from tests.pg_drop import drop_database_if_exists

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_strategy_lifecycle"
_PRE_MIGRATION_DB_PREFIX = "strategy_manager_test_strategy_lifecycle_pre"
_MIGRATION_PATH = _BACKEND_DIR / "migrations" / "versions" / "0024_strategy_lifecycle.py"

_POOL = {"exchange": "pionex", "venue": "spot", "settlement_currency": "USDT"}

_ARCHIVED_CHECK = "ck_strategies_archived_requires_disabled"
_EVENTS_TABLE = "strategy_enablement_events"
_EVENTS_INDEX = "ix_strategy_enablement_events_strategy_occurred_at"

# ``alembic.ini``'s ``formatter_generic`` is ``%(levelname)-5.5s ...`` --
# the ``.5`` precision TRUNCATES "WARNING" to 5 characters, so the level
# label that actually reaches ``alembic upgrade`` output is "WARNI", not
# "WARNING". Asserting the truncated label (rather than skipping the level
# check) is what proves the line is logged at WARNING, not INFO.
_WARNING_LEVEL_LABEL = "WARNI"


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
        raise RuntimeError(
            f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
        )


def _constraint_name(error: IntegrityError) -> str | None:
    """The asyncpg driver wraps its own ``PostgresError`` (which carries
    ``constraint_name`` directly) as ``__cause__`` of SQLAlchemy's DBAPI
    wrapper exception -- see ``test_0023_booking_proposals.py``'s identical
    helper. Reading it here identifies the violated constraint BY NAME,
    never by message text (this change's binding testing rule)."""
    cause = error.orig.__cause__
    return getattr(cause, "constraint_name", None)


def _pgcode(error: DBAPIError) -> str | None:
    """The PostgreSQL SQLSTATE of the underlying driver error -- proves the
    append-only trigger raised exactly ``restrict_violation`` (``23001``),
    not merely some exception with a matching message (same helper as
    ``tests/ledger/infrastructure/test_append_only_guard.py``)."""
    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


# --------------------------------------------------------------------------
# Fixtures: a shared database already migrated to head, for structural and
# downgrade-refusal tests.
# --------------------------------------------------------------------------


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


async def _seed_strategy(
    conn: AsyncConnection, *, enabled: bool, strategy_id: UUID | None = None
) -> UUID:
    strategy_id = strategy_id or uuid4()
    await conn.execute(
        text(
            "INSERT INTO strategies "
            "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
            "VALUES (:id, :name, :exchange, :venue, :settlement_currency, :enabled, 'PARTIAL')"
        ),
        {"id": strategy_id, "name": f"strategy-{strategy_id}", "enabled": enabled, **_POOL},
    )
    return strategy_id


async def _insert_event(conn: AsyncConnection, *, strategy_id: UUID, origin: str) -> UUID:
    event_id = uuid4()
    await conn.execute(
        text(
            f"INSERT INTO {_EVENTS_TABLE} (id, strategy_id, enabled, origin) "
            "VALUES (:id, :strategy_id, true, :origin)"
        ),
        {"id": event_id, "strategy_id": strategy_id, "origin": origin},
    )
    return event_id


# --------------------------------------------------------------------------
# Fixture: dedicated throwaway databases migrated only to 0023, so a test
# can insert its own pre-migration rows before running 0024 itself.
# --------------------------------------------------------------------------


@pytest.fixture
def pre_migration_db_factory() -> Iterator[Callable[[str], str]]:
    dev_url = get_settings().database_url
    maintenance_dsn = _maintenance_dsn(dev_url)
    created: list[str] = []

    def make(suffix: str) -> str:
        name = f"{_PRE_MIGRATION_DB_PREFIX}_{suffix}"
        url = _database_url(dev_url, name)
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))
        asyncio.run(_create_database(maintenance_dsn, name))
        _run_alembic_ok(url, "upgrade", "0023")
        created.append(name)
        return url

    yield make

    for name in created:
        asyncio.run(drop_database_if_exists(maintenance_dsn, name))


async def _seed_pre_migration_strategy(
    engine_url: str,
    strategy_id: UUID,
    *,
    enabled: bool,
    symbols: Sequence[str] = (),
) -> None:
    engine = create_async_engine(engine_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "INSERT INTO strategies "
                    "(id, name, exchange, venue, settlement_currency, enabled, fill_mode) "
                    "VALUES (:id, :name, :exchange, :venue, :settlement_currency, "
                    ":enabled, 'PARTIAL')"
                ),
                {
                    "id": strategy_id,
                    "name": f"strategy-{strategy_id}",
                    "enabled": enabled,
                    **_POOL,
                },
            )
            for index, symbol in enumerate(symbols):
                await connection.execute(
                    text(
                        "INSERT INTO signals "
                        "(id, strategy_id, idempotency_key, raw_payload, action, contracts, "
                        "position_size, price, symbol, signal_type) "
                        "VALUES (:sid, :strategy_id, :idempotency_key, '{}', 'buy', 1, 1, 1, "
                        ":symbol, :signal_type)"
                    ),
                    {
                        "sid": uuid4(),
                        "strategy_id": strategy_id,
                        "idempotency_key": f"k-{strategy_id}-{index}",
                        "symbol": symbol,
                        "signal_type": str(strategy_id),
                    },
                )
            await connection.commit()
    finally:
        await engine.dispose()


async def _read_allowed_pairs(engine_url: str, strategy_id: UUID) -> list[str]:
    engine = create_async_engine(engine_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            return (
                await connection.execute(
                    text("SELECT allowed_pairs FROM strategies WHERE id = :id"),
                    {"id": strategy_id},
                )
            ).scalar_one()
    finally:
        await engine.dispose()


async def _read_events(engine_url: str, strategy_id: UUID) -> list[dict[str, object]]:
    engine = create_async_engine(engine_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        f"SELECT enabled, origin FROM {_EVENTS_TABLE} "
                        "WHERE strategy_id = :id"
                    ),
                    {"id": strategy_id},
                )
            ).mappings().all()
            return [dict(row) for row in rows]
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------
# 2a.3 / 2a.4 / orchestrator point 2 -- seeding from signal history
# --------------------------------------------------------------------------


def test_seeding_uses_distinct_market_key_normalized_symbols_from_signals(
    pre_migration_db_factory: Callable[[str], str],
) -> None:
    url = pre_migration_db_factory("distinct_symbols")
    strategy_id = uuid4()
    asyncio.run(
        _seed_pre_migration_strategy(
            url, strategy_id, enabled=False, symbols=["ETHUSDT", "ETHUSDT.P", "SOLUSDT"]
        )
    )

    result = _run_alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr

    # Orchestrator point 3: the seeding WARNING must actually reach
    # ``alembic upgrade head``'s own output, not merely a caplog record.
    output = result.stdout + result.stderr
    assert _WARNING_LEVEL_LABEL in output
    assert str(strategy_id) in output
    assert "ETHUSDT" in output
    assert "SOLUSDT" in output

    allowed_pairs = asyncio.run(_read_allowed_pairs(url, strategy_id))
    assert allowed_pairs == ["ETHUSDT", "SOLUSDT"]


def test_strategy_with_no_signals_seeded_empty(
    pre_migration_db_factory: Callable[[str], str],
) -> None:
    url = pre_migration_db_factory("no_signals")
    strategy_id = uuid4()
    asyncio.run(_seed_pre_migration_strategy(url, strategy_id, enabled=False, symbols=()))

    _run_alembic_ok(url, "upgrade", "head")

    allowed_pairs = asyncio.run(_read_allowed_pairs(url, strategy_id))
    assert allowed_pairs == []


def test_unparseable_signal_symbol_logs_warning_and_is_skipped_during_seeding(
    pre_migration_db_factory: Callable[[str], str],
) -> None:
    """Orchestrator addition point 2: an empty ``signals.symbol`` (nothing in
    migration 0002's schema forbids it) normalizes to nothing meaningful --
    the frozen copy returns ``None`` for it, per
    ``test_frozen_normalizer_matches_market_key_across_spellings``'s own
    contract. Seeding must skip it with a WARNING naming the strategy and
    the raw symbol, and must still seed the other, valid symbol."""
    url = pre_migration_db_factory("unparseable")
    strategy_id = uuid4()
    asyncio.run(
        _seed_pre_migration_strategy(
            url, strategy_id, enabled=False, symbols=["", "ETHUSDT"]
        )
    )

    result = _run_alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr

    output = result.stdout + result.stderr
    assert _WARNING_LEVEL_LABEL in output
    assert str(strategy_id) in output
    assert "could not be normalized" in output

    allowed_pairs = asyncio.run(_read_allowed_pairs(url, strategy_id))
    assert allowed_pairs == ["ETHUSDT"]


# --------------------------------------------------------------------------
# 2a.5 / orchestrator point 1 -- the frozen normalization copy
# --------------------------------------------------------------------------


def test_seeding_uses_a_frozen_normalization_copy_not_application_import() -> None:
    """Migrations must not import application code that can change later
    (design.md § 6 "Seeding (decision 13)"). Checks actual ``import``/
    ``from ... import`` statement lines only -- not the docstring, which is
    free to NAME ``strategy_manager.execution...`` in prose to explain why
    it is deliberately not imported."""
    source = _MIGRATION_PATH.read_text(encoding="utf-8")
    import_lines = [
        line
        for line in source.splitlines()
        if line.strip().startswith(("import ", "from "))
    ]
    assert not any("strategy_manager.execution" in line for line in import_lines)
    assert not any("strategy_manager.reconciliation" in line for line in import_lines)


def _load_migration_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_migration_0024_strategy_lifecycle", _MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SPELLING_TABLE = [
    "SOLUSDT.P",
    "SOLUSDT",
    "SOLUSDT_PERP",
    "solusdt.p",
    "SoLuSdT_PeRp",
    "  SOLUSDT  ",
    "BTC_USDT",
    "btc_usdt_perp",
    "ETHUSDT.P",
    "ethusdt_perp",
]


def test_frozen_normalizer_matches_market_key_across_spellings() -> None:
    """Orchestrator addition point 1: a frozen copy that DRIFTS from
    ``market_key()`` would seed pairs that never match a real signal's
    normalized symbol, and PR 5's allowlist gate would then refuse every
    signal of that strategy with no hint why. Runs BOTH implementations
    against the same table of spellings and fails the instant they
    diverge -- lives outside the migration module itself, per the
    orchestrator's instruction."""
    module = _load_migration_module()

    for symbol in _SPELLING_TABLE:
        assert module._frozen_market_key(symbol) == market_key(symbol), symbol


def test_frozen_normalizer_returns_none_for_a_symbol_that_normalizes_to_empty() -> None:
    module = _load_migration_module()

    assert module._frozen_market_key("") is None
    assert module._frozen_market_key(".P") is None


# --------------------------------------------------------------------------
# 2a.6 -- CHECK constraints, events table, triggers
# --------------------------------------------------------------------------


async def test_archived_at_check_constraint_refuses_archived_and_enabled(
    conn: AsyncConnection,
) -> None:
    strategy_id = await _seed_strategy(conn, enabled=True)
    await conn.commit()

    with pytest.raises(IntegrityError) as exc_info:
        await conn.execute(
            text("UPDATE strategies SET archived_at = now() WHERE id = :id"),
            {"id": strategy_id},
        )
    assert _constraint_name(exc_info.value) == _ARCHIVED_CHECK
    await conn.rollback()


async def test_enablement_events_table_and_index_created(conn: AsyncConnection) -> None:
    table_exists = (
        await conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :name"
            ),
            {"name": _EVENTS_TABLE},
        )
    ).scalar_one_or_none()
    assert table_exists == 1

    index_exists = (
        await conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE tablename = :table AND indexname = :name"
            ),
            {"table": _EVENTS_TABLE, "name": _EVENTS_INDEX},
        )
    ).scalar_one_or_none()
    assert index_exists == 1


async def test_append_only_trigger_refuses_update(conn: AsyncConnection) -> None:
    strategy_id = await _seed_strategy(conn, enabled=False)
    event_id = await _insert_event(conn, strategy_id=strategy_id, origin="OBSERVED")
    await conn.commit()

    with pytest.raises(DBAPIError, match="(?i)append-only") as exc_info:
        await conn.execute(
            text(f"UPDATE {_EVENTS_TABLE} SET enabled = false WHERE id = :id"),
            {"id": event_id},
        )
    assert _pgcode(exc_info.value) == "23001"  # restrict_violation
    await conn.rollback()


async def test_append_only_trigger_refuses_delete(conn: AsyncConnection) -> None:
    strategy_id = await _seed_strategy(conn, enabled=False)
    event_id = await _insert_event(conn, strategy_id=strategy_id, origin="OBSERVED")
    await conn.commit()

    with pytest.raises(DBAPIError, match="(?i)append-only") as exc_info:
        await conn.execute(text(f"DELETE FROM {_EVENTS_TABLE} WHERE id = :id"), {"id": event_id})
    assert _pgcode(exc_info.value) == "23001"  # restrict_violation
    await conn.rollback()


async def test_no_truncate_trigger_exists(conn: AsyncConnection) -> None:
    """Deliberate omission (design.md § 9): eight integration conftests
    ``TRUNCATE strategies ... CASCADE`` (e.g.
    ``tests/strategies/infrastructure/conftest.py``), and a TRUNCATE guard
    on this table would break every one of them. The threat an audit trail
    defends against is an application bug updating or deleting a row, not
    an operator truncating -- the ledger keeps the stronger guard because
    it is money."""
    found = (
        await conn.execute(
            text(
                "SELECT 1 FROM pg_trigger WHERE tgrelid = "
                "(:table)::regclass AND tgname ILIKE '%truncate%'"
            ),
            {"table": _EVENTS_TABLE},
        )
    ).scalar_one_or_none()
    assert found is None


# --------------------------------------------------------------------------
# 2a.7 -- BASELINE event at migration time
# --------------------------------------------------------------------------


def test_baseline_event_written_for_every_currently_enabled_strategy_at_migration_time(
    pre_migration_db_factory: Callable[[str], str],
) -> None:
    url = pre_migration_db_factory("baseline")
    enabled_id = uuid4()
    disabled_id = uuid4()
    asyncio.run(_seed_pre_migration_strategy(url, enabled_id, enabled=True))
    asyncio.run(_seed_pre_migration_strategy(url, disabled_id, enabled=False))

    _run_alembic_ok(url, "upgrade", "head")

    enabled_events = asyncio.run(_read_events(url, enabled_id))
    assert len(enabled_events) == 1
    assert enabled_events[0]["enabled"] is True
    assert enabled_events[0]["origin"] == "BASELINE"

    disabled_events = asyncio.run(_read_events(url, disabled_id))
    assert disabled_events == []


# --------------------------------------------------------------------------
# 2a.8 -- downgrade refuses while any OBSERVED event exists
# --------------------------------------------------------------------------


async def test_downgrade_refuses_while_any_observed_event_exists_naming_count(
    conn: AsyncConnection, database_url: str
) -> None:
    strategy_id = await _seed_strategy(conn, enabled=False)
    await _insert_event(conn, strategy_id=strategy_id, origin="OBSERVED")
    await conn.commit()

    refused = _run_alembic(database_url, "downgrade", "0023")
    assert refused.returncode != 0
    output = refused.stdout + refused.stderr
    assert "1" in output
    assert "OBSERVED" in output


# --------------------------------------------------------------------------
# Owner correction (2026-09-25): downgrade must LOG what it discards, never
# silently drop owner-pruned allowed_pairs/archived_at with no trace.
# --------------------------------------------------------------------------


async def _set_archived_at(engine_url: str, strategy_id: UUID) -> None:
    engine = create_async_engine(engine_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text("UPDATE strategies SET archived_at = now() WHERE id = :id"),
                {"id": strategy_id},
            )
            await connection.commit()
    finally:
        await engine.dispose()


def test_downgrade_logs_discarded_allowed_pairs_and_archived_at_without_refusing(
    pre_migration_db_factory: Callable[[str], str],
) -> None:
    """After deploy the owner prunes the seeded allowed pairs
    (PUT .../allowed-pairs, unit 2e) and may archive strategies. A
    downgrade that just drops ``allowed_pairs``/``archived_at`` with no
    trace, followed by a later re-upgrade, would silently RE-SEED
    allowed_pairs from signal history -- restoring exactly what the owner
    pruned. The downgrade must NOT refuse (rollback must stay possible),
    but it must log what it is about to discard."""
    url = pre_migration_db_factory("downgrade_discards")
    strategy_id = uuid4()
    # Seeded from the TradingView spelling "ETHUSDT.P"; the seeded
    # allowed_pairs value is market_key()-normalized to "ETHUSDT" -- a
    # DIFFERENT spelling, proving the downgrade log reports the CURRENT
    # column value, not a re-derivation/echo of the raw signal symbol.
    asyncio.run(
        _seed_pre_migration_strategy(url, strategy_id, enabled=False, symbols=["ETHUSDT.P"])
    )

    _run_alembic_ok(url, "upgrade", "head")
    asyncio.run(_set_archived_at(url, strategy_id))

    result = _run_alembic(url, "downgrade", "0023")
    assert result.returncode == 0, result.stdout + result.stderr  # never refuses

    output = result.stdout + result.stderr
    assert _WARNING_LEVEL_LABEL in output
    assert str(strategy_id) in output
    assert "ETHUSDT" in output
    assert "ETHUSDT.P" not in output  # the CURRENT (normalized) value, not the raw signal
    assert "archived_at" in output
    assert "re-upgrade" in output.lower()
    assert "restore" in output.lower()

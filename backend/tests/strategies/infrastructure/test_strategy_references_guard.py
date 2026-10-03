"""Exhaustiveness guard for the delete check (design.md addendum 9x, § C, D5).

``StrategyHistory`` counts what references a strategy. The foreign keys into
``strategies`` are the guarantee that nothing is missed; the count is the
readable refusal. This module reads the foreign keys from ``pg_constraint`` on
a database migrated to ``head`` -- the ORM-built schema lacks three of them --
and fails when one is not covered by a counted kind, so a later migration
cannot leave the delete check silently stale.

When this fails: a migration added a reference to ``strategies``. Extend
``StrategyHistory`` (a new field and a count on the owning module's
repository), the ``StrategyHistoryAdapter``, and ``COUNTED_STRATEGY_REFERENCES``.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import fields

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.strategies.application.ports import StrategyHistory
from strategy_manager.strategies.infrastructure.history_adapter import (
    COUNTED_STRATEGY_REFERENCES,
)
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

_EXTEND_THE_HISTORY = (
    "extend StrategyHistory, StrategyHistoryAdapter and COUNTED_STRATEGY_REFERENCES "
    "so DeleteStrategy counts this reference"
)


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_strategy_references") as url:
        yield url


@pytest.fixture
async def conn(head_database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _foreign_keys_into_strategies(conn: AsyncConnection) -> dict[str, tuple[str, str]]:
    """Constraint name -> ``(referencing table, ON DELETE action code)``.
    ``a`` is ``NO ACTION``."""
    rows = await conn.execute(
        text(
            "SELECT c.conname, c.conrelid::regclass::text AS referencing_table, "
            "c.confdeltype::text AS on_delete "
            "FROM pg_constraint c "
            "WHERE c.contype = 'f' AND c.confrelid = 'strategies'::regclass"
        )
    )
    return {row.conname: (row.referencing_table, row.on_delete) for row in rows}


async def uncounted_references(conn: AsyncConnection) -> set[str]:
    """Foreign keys into ``strategies`` that no counted kind covers."""
    present = await _foreign_keys_into_strategies(conn)
    return set(present) - set(COUNTED_STRATEGY_REFERENCES)


def _message(unknown: set[str]) -> str:
    return f"foreign key(s) into strategies not counted: {sorted(unknown)}; {_EXTEND_THE_HISTORY}"


async def test_every_foreign_key_into_strategies_is_one_the_history_check_counts(
    conn: AsyncConnection,
) -> None:
    present = await _foreign_keys_into_strategies(conn)

    assert set(present) == {
        "fk_signals_strategy",
        "fk_reservations_strategy",
        "fk_ledger_entries_strategy",
        "fk_booking_proposals_strategy",
        "fk_strategy_enablement_events_strategy",
    }
    assert await uncounted_references(conn) == set(), _message(await uncounted_references(conn))
    assert set(COUNTED_STRATEGY_REFERENCES) == set(present), (
        "COUNTED_STRATEGY_REFERENCES names a constraint the database no longer has"
    )
    assert {on_delete for _, on_delete in present.values()} == {"a"}
    assert {name: table for name, (table, _) in present.items()} == {
        name: table for name, (table, _) in COUNTED_STRATEGY_REFERENCES.items()
    }


def test_every_counted_reference_names_a_strategy_history_field() -> None:
    history_fields = {field.name for field in fields(StrategyHistory)}

    counted_kinds = {kind for _, kind in COUNTED_STRATEGY_REFERENCES.values()}

    # ``execution_attempts`` is the one kind that reaches a strategy through
    # other rows, so no foreign key into ``strategies`` names it.
    assert counted_kinds == history_fields - {"execution_attempts"}


async def test_every_strategy_id_column_belongs_to_a_counted_table(
    conn: AsyncConnection,
) -> None:
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_name = 'strategy_id'"
        )
    )
    tables = {row.table_name for row in rows}
    counted_tables = {table for table, _ in COUNTED_STRATEGY_REFERENCES.values()}

    assert tables == counted_tables, (
        f"strategy_id column(s) outside the counted tables: {sorted(tables - counted_tables)}; "
        f"{_EXTEND_THE_HISTORY}"
    )
    assert tables


async def test_execution_attempts_reach_a_strategy_only_through_reservations_and_signals(
    conn: AsyncConnection,
) -> None:
    rows = await conn.execute(
        text(
            "SELECT c.confrelid::regclass::text AS target "
            "FROM pg_constraint c "
            "WHERE c.contype = 'f' AND c.conrelid = 'execution_attempts'::regclass"
        )
    )
    targets = {row.target for row in rows}
    has_strategy_id = await conn.scalar(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'execution_attempts' "
            "AND column_name = 'strategy_id'"
        )
    )

    assert targets == {"reservations", "signals"}, (
        f"execution_attempts now references {sorted(targets)}; "
        f"{_EXTEND_THE_HISTORY}"
    )
    assert has_strategy_id == 0


async def test_the_guard_reports_a_reference_added_in_a_transaction(
    conn: AsyncConnection,
) -> None:
    await conn.execute(text("CREATE TABLE x (strategy_id uuid REFERENCES strategies(id))"))
    try:
        unknown = await uncounted_references(conn)
    finally:
        await conn.rollback()

    assert unknown == {"x_strategy_id_fkey"}, _message(unknown)
    assert "extend StrategyHistory" in _message(unknown)
    assert await conn.scalar(text("SELECT to_regclass('x')")) is None

"""Integration test (DB-level) proving the hard constraint from design.md
§ "strategy_id derives from signal_type": strategy registration MUST set
``strategies.id`` explicitly to the signal's ``strategy_id``
(== ``UUID(signal_type)``). A matching id lets migration 0003's deferred
``fk_signals_strategy`` apply cleanly; a generated id makes it fail
(tasks.md 3.0).

Runs the exact DDL sequence migration 0003 uses, against uniquely-prefixed
tables in the ``public`` schema (the ``strategy_manager`` role has no
``CREATE`` privilege on the database itself, only inside ``public``, so a
dedicated schema per test is not available here). This is a DB/infra proof
test with no corresponding application code — it validates the invariant
migration 0003 depends on, in isolation from the ORM and from strategy
registration code.
"""

import re
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from strategy_manager.shared.config import get_settings

pytestmark = pytest.mark.integration

TEST_DB_NAME = "strategy_manager_test"
_test_db_ready = False


def _test_database_url(dev_url: str) -> str:
    return re.sub(r"/[^/?]+(\?.*)?$", rf"/{TEST_DB_NAME}\1", dev_url)


async def _ensure_test_database_exists(dev_url: str) -> None:
    global _test_db_ready
    if _test_db_ready:
        return
    dsn = dev_url.replace("postgresql+asyncpg://", "postgresql://")
    maintenance_dsn = re.sub(r"/[^/?]+(\?.*)?$", r"/postgres\1", dsn)
    conn = await asyncpg.connect(maintenance_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()
    _test_db_ready = True


@pytest.fixture
async def conn() -> AsyncIterator[AsyncConnection]:
    settings = get_settings()
    test_url = _test_database_url(settings.database_url)
    await _ensure_test_database_exists(settings.database_url)

    engine = create_async_engine(test_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
    await engine.dispose()


async def _create_tables(conn: AsyncConnection, prefix: str, strategy_id: object) -> None:
    """Mirrors migration 0003's DDL: signals pre-exists (0002), then
    strategies is created, a signal referencing ``strategy_id`` is inserted,
    and finally the deferred FK is added — exactly 0003's own statement
    order."""

    await conn.execute(
        text(
            f"CREATE TABLE {prefix}_strategies "
            "(id uuid PRIMARY KEY DEFAULT gen_random_uuid())"
        )
    )
    await conn.execute(
        text(f"CREATE TABLE {prefix}_signals (id uuid PRIMARY KEY, strategy_id uuid NOT NULL)")
    )
    await conn.execute(
        text(f"INSERT INTO {prefix}_signals (id, strategy_id) VALUES (gen_random_uuid(), :sid)"),
        {"sid": strategy_id},
    )


async def test_strategy_id_matching_signal_type_lets_the_fk_apply_cleanly(
    conn: AsyncConnection,
) -> None:
    prefix = "test_0003_match"
    strategy_id = uuid4()
    await conn.execute(text(f"DROP TABLE IF EXISTS {prefix}_signals, {prefix}_strategies CASCADE"))
    await _create_tables(conn, prefix, strategy_id)

    # Registration sets strategies.id EXPLICITLY to the signal's strategy_id
    # — never the gen_random_uuid() server default.
    await conn.execute(
        text(f"INSERT INTO {prefix}_strategies (id) VALUES (:sid)"), {"sid": strategy_id}
    )

    await conn.execute(
        text(
            f"ALTER TABLE {prefix}_signals ADD CONSTRAINT fk_signals_strategy_match "
            f"FOREIGN KEY (strategy_id) REFERENCES {prefix}_strategies (id)"
        )
    )  # no raise: the FK found a matching row

    await conn.execute(text(f"DROP TABLE {prefix}_signals, {prefix}_strategies CASCADE"))
    await conn.commit()


async def test_generated_strategy_id_makes_the_fk_fail(conn: AsyncConnection) -> None:
    prefix = "test_0003_mismatch"
    strategy_id = uuid4()
    await conn.execute(text(f"DROP TABLE IF EXISTS {prefix}_signals, {prefix}_strategies CASCADE"))
    await _create_tables(conn, prefix, strategy_id)

    # Registration relies on the gen_random_uuid() server default instead of
    # the signal's strategy_id — the exact mistake the hard constraint warns
    # against.
    await conn.execute(text(f"INSERT INTO {prefix}_strategies DEFAULT VALUES"))

    with pytest.raises(IntegrityError):
        await conn.execute(
            text(
                f"ALTER TABLE {prefix}_signals ADD CONSTRAINT fk_signals_strategy_mismatch "
                f"FOREIGN KEY (strategy_id) REFERENCES {prefix}_strategies (id)"
            )
        )

    # The aborted transaction already rolled back the CREATE/INSERT above —
    # nothing left to clean up.
    await conn.rollback()

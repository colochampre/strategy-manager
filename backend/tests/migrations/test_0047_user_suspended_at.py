"""Migration ``0047`` -- when the admin suspended an account (public-site LS9, PS.13 S2).

* ``users.suspended_at`` is nullable and nothing is backfilled: nobody is suspended.
* Nothing else is stored: no reason, no who.
* The downgrade refuses while anyone is suspended: dropping the column would lift
  every suspension without a word. With nobody suspended it removes the column and
  leaves the users as 0046 had them.

Real PostgreSQL, one database per scenario, seeded at ``0046``.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_user_suspended_at"
_USER_COLUMNS = "id, email, created_at, last_seen_at, mode, display_name, deleted_at, cuit"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url, "DRY_RUN": "false"},
        capture_output=True,
        text=True,
        check=False,
    )


def _query(
    database_url: str, sql: str, params: dict[str, Any] | None = None
) -> list[tuple[Any, ...]]:
    async def run() -> list[tuple[Any, ...]]:
        engine = create_async_engine(database_url, pool_pre_ping=True)
        try:
            async with engine.begin() as connection:
                result = await connection.execute(text(sql), params or {})
                return [tuple(row) for row in result] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _seed_user(database_url: str, email: str, name: str | None = None) -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email, display_name) VALUES (:id, :email, :name)",
        {"id": user_id, "email": email, "name": name},
    )
    return user_id


def _has_column(database_url: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'suspended_at'",
        )
    )


@pytest.fixture
def at_0046() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0046") as url:
        yield url


def test_upgrade_suspends_nobody_and_changes_no_user(at_0046: str) -> None:
    _seed_user(at_0046, "owner@example.com", "Owner")
    _seed_user(at_0046, "someone@example.com")
    before = _query(at_0046, f"SELECT {_USER_COLUMNS} FROM users ORDER BY email")

    result = _alembic(at_0046, "upgrade", "0047")

    assert result.returncode == 0, result.stderr
    assert _query(at_0046, f"SELECT {_USER_COLUMNS} FROM users ORDER BY email") == before
    assert _query(at_0046, "SELECT count(*) FROM users WHERE suspended_at IS NOT NULL") == [(0,)]


def test_the_column_is_a_nullable_instant(at_0046: str) -> None:
    result = _alembic(at_0046, "upgrade", "0047")

    assert result.returncode == 0, result.stderr
    assert _query(
        at_0046,
        "SELECT data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'suspended_at'",
    ) == [("timestamp with time zone", "YES")]


def test_downgrade_with_nobody_suspended_removes_the_column_and_keeps_the_users(
    at_0046: str,
) -> None:
    assert _alembic(at_0046, "upgrade", "0047").returncode == 0
    _seed_user(at_0046, "owner@example.com", "Owner")
    before = _query(at_0046, "SELECT id, email, display_name FROM users ORDER BY email")

    result = _alembic(at_0046, "downgrade", "0046")

    assert result.returncode == 0, result.stderr
    assert not _has_column(at_0046)
    assert _query(at_0046, "SELECT id, email, display_name FROM users ORDER BY email") == before


def test_downgrade_refuses_while_anyone_is_suspended(at_0046: str) -> None:
    assert _alembic(at_0046, "upgrade", "0047").returncode == 0
    user_id = _seed_user(at_0046, "someone@example.com")
    _query(at_0046, "UPDATE users SET suspended_at = now() WHERE id = :id", {"id": user_id})

    result = _alembic(at_0046, "downgrade", "0046")

    assert result.returncode != 0
    assert "Refusing to downgrade 0047" in result.stdout + result.stderr
    assert _has_column(at_0046)
    assert _query(
        at_0046, "SELECT suspended_at IS NOT NULL FROM users WHERE id = :id", {"id": user_id}
    ) == [(True,)]

"""Migration ``0045`` -- when a user deleted their account (account-deletion S3).

* ``users.deleted_at`` is nullable and nothing is backfilled: nobody has deleted one.
* A CHECK holds a deleted row to naming nobody: no display name, and the e-mail
  ``deleted-<id>@invalid``.
* The downgrade removes both and leaves the users as they were.

Real PostgreSQL, one database per scenario, seeded at ``0044``.
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_user_deleted_at"
_CHECK = "ck_users_deleted_names_nobody"


def _alembic(database_url: str, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url, "DRY_RUN": "false"},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


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


def _mark_deleted(database_url: str, user_id: UUID, email: str, name: str | None) -> None:
    _query(
        database_url,
        "UPDATE users SET deleted_at = now(), email = :email, display_name = :name WHERE id = :id",
        {"email": email, "name": name, "id": user_id},
    )


def _violated(database_url: str, user_id: UUID, email: str, name: str | None) -> str | None:
    """The constraint the write trips, BY NAME, never by message text."""
    with pytest.raises(DBAPIError) as caught:
        _mark_deleted(database_url, user_id, email, name)
    return getattr(caught.value.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _has_column(database_url: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'deleted_at'",
        )
    )


def _has_check(database_url: str) -> bool:
    return bool(
        _query(database_url, "SELECT 1 FROM pg_constraint WHERE conname = :n", {"n": _CHECK})
    )


@pytest.fixture
def at_0044() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0044") as url:
        yield url


def test_upgrade_marks_nobody_deleted_and_changes_no_user(at_0044: str) -> None:
    user_id = _seed_user(at_0044, "owner@example.com", "Owner")
    columns = "id, email, created_at, last_seen_at, mode, display_name"
    before = _query(at_0044, f"SELECT {columns} FROM users")

    _alembic(at_0044, "upgrade", "0045")

    assert _query(at_0044, f"SELECT {columns} FROM users") == before
    assert _query(at_0044, "SELECT deleted_at FROM users WHERE id = :id", {"id": user_id}) == [
        (None,)
    ]


def test_a_deleted_row_that_names_nobody_is_accepted(at_0044: str) -> None:
    _alembic(at_0044, "upgrade", "0045")
    user_id = _seed_user(at_0044, "owner@example.com", "Owner")

    _mark_deleted(at_0044, user_id, f"deleted-{user_id}@invalid", None)

    assert _query(
        at_0044, "SELECT email, display_name FROM users WHERE id = :id", {"id": user_id}
    ) == [(f"deleted-{user_id}@invalid", None)]


def test_a_deleted_row_keeping_its_real_e_mail_is_refused(at_0044: str) -> None:
    _alembic(at_0044, "upgrade", "0045")
    user_id = _seed_user(at_0044, "owner@example.com")

    assert _violated(at_0044, user_id, "owner@example.com", None) == _CHECK


def test_a_deleted_row_keeping_its_name_is_refused(at_0044: str) -> None:
    _alembic(at_0044, "upgrade", "0045")
    user_id = _seed_user(at_0044, "owner@example.com", "Owner")

    assert _violated(at_0044, user_id, f"deleted-{user_id}@invalid", "Owner") == _CHECK


def test_a_deleted_row_with_another_users_placeholder_is_refused(at_0044: str) -> None:
    _alembic(at_0044, "upgrade", "0045")
    user_id = _seed_user(at_0044, "owner@example.com")

    assert _violated(at_0044, user_id, f"deleted-{uuid4()}@invalid", None) == _CHECK


def test_downgrade_removes_the_column_and_the_check_and_keeps_the_users(at_0044: str) -> None:
    _alembic(at_0044, "upgrade", "0045")
    _seed_user(at_0044, "owner@example.com", "Owner")
    before = _query(at_0044, "SELECT id, email, display_name FROM users")

    _alembic(at_0044, "downgrade", "0044")

    assert not _has_column(at_0044)
    assert not _has_check(at_0044)
    assert _query(at_0044, "SELECT id, email, display_name FROM users") == before

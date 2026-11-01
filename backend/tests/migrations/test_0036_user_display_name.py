"""Migration ``0036`` -- a user's display name (multi-user decision 27; tasks.md F.1).

* ``users.display_name`` is nullable and nothing is backfilled: nobody has a name yet.
* A CHECK stands behind ``normalize_display_name``.
* A unique index on ``lower()`` lets one name be taken once, whatever its case.
* The downgrade removes all three and leaves the users as they were.

Real PostgreSQL, one database per scenario, seeded at ``0035``.
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
_DB_NAME = "strategy_manager_test_display_name"
_CHECK = "ck_users_display_name_shape"
_INDEX = "ux_users_display_name_lower"


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


def _seed_user(database_url: str, email: str) -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email) VALUES (:id, :email)",
        {"id": user_id, "email": email},
    )
    return user_id


def _set_name(database_url: str, user_id: UUID, name: str) -> None:
    _query(
        database_url,
        "UPDATE users SET display_name = :name WHERE id = :id",
        {"name": name, "id": user_id},
    )


def _violated(database_url: str, user_id: UUID, name: str) -> str | None:
    """The constraint a write of ``name`` trips, BY NAME, never by message text."""
    with pytest.raises(DBAPIError) as caught:
        _set_name(database_url, user_id, name)
    return getattr(caught.value.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _has_column(database_url: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'display_name'",
        )
    )


@pytest.fixture
def at_0035() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0035") as url:
        yield url


def test_upgrade_gives_nobody_a_name_and_changes_no_user(at_0035: str) -> None:
    user_id = _seed_user(at_0035, "owner@example.com")
    before = _query(at_0035, "SELECT id, email, created_at, last_seen_at, mode FROM users")

    _alembic(at_0035, "upgrade", "0036")

    assert _query(at_0035, "SELECT id, email, created_at, last_seen_at, mode FROM users") == before
    assert _query(at_0035, "SELECT display_name FROM users WHERE id = :id", {"id": user_id}) == [
        (None,)
    ]


@pytest.mark.parametrize(
    "name", [" Ana", "Ana ", "An", "a" * 31, "ana@example.com"], ids=repr
)
def test_the_check_refuses_a_name_the_domain_refuses(at_0035: str, name: str) -> None:
    user_id = _seed_user(at_0035, "owner@example.com")
    _alembic(at_0035, "upgrade", "0036")

    assert _violated(at_0035, user_id, name) == _CHECK


def test_the_check_takes_the_shortest_and_the_longest_name(at_0035: str) -> None:
    user_id = _seed_user(at_0035, "owner@example.com")
    _alembic(at_0035, "upgrade", "0036")

    _set_name(at_0035, user_id, "Ana")
    _set_name(at_0035, user_id, "a" * 30)

    assert _query(at_0035, "SELECT display_name FROM users") == [("a" * 30,)]


def test_a_name_is_taken_once_whatever_its_case(at_0035: str) -> None:
    first = _seed_user(at_0035, "first@example.com")
    second = _seed_user(at_0035, "second@example.com")
    _alembic(at_0035, "upgrade", "0036")
    _set_name(at_0035, first, "Ana")

    assert _violated(at_0035, second, "ANA") == _INDEX


def test_any_number_of_users_can_have_no_name(at_0035: str) -> None:
    _seed_user(at_0035, "first@example.com")
    _seed_user(at_0035, "second@example.com")

    _alembic(at_0035, "upgrade", "0036")

    assert _query(at_0035, "SELECT count(*) FROM users WHERE display_name IS NULL") == [(2,)]


def test_downgrade_removes_everything_and_the_upgrade_runs_again(at_0035: str) -> None:
    user_id = _seed_user(at_0035, "owner@example.com")
    _alembic(at_0035, "upgrade", "0036")
    _set_name(at_0035, user_id, "Ana")

    _alembic(at_0035, "downgrade", "0035")

    assert not _has_column(at_0035)
    assert _query(at_0035, "SELECT 1 FROM pg_indexes WHERE indexname = :n", {"n": _INDEX}) == []
    assert _query(at_0035, "SELECT 1 FROM pg_constraint WHERE conname = :n", {"n": _CHECK}) == []
    assert _query(at_0035, "SELECT email FROM users") == [("owner@example.com",)]

    _alembic(at_0035, "upgrade", "0036")

    assert _has_column(at_0035)

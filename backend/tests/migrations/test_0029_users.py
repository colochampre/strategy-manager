"""Migration ``0029`` -- the ``users`` table (multi-user design AD1; tasks.md A.3).

A user is the e-mail Cloudflare Access verified (decision 1). The table holds
one row per address, in its one normal spelling, and nothing that could
authenticate anyone: there is no password column, by design.

The migration creates the table and nothing else. The owner's row is created the
way every user's is, on their first signed-in request, so the migration needs no
setting and a fresh database migrates exactly like production.

Real PostgreSQL, following ``test_0028_enablement_events_cascade.py``: one
module-scoped database at ``head`` for the constraints, and a throwaway one for
the downgrade.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_head_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_NAME = "strategy_manager_test_users"
_THROWAWAY_DB_PREFIX = "strategy_manager_test_users_throwaway"

_EMAIL_UNIQUE = "ux_users_email"
_EMAIL_LOWER = "ck_users_email_normalized"


def _run_alembic_ok(database_url: str, *args: str) -> None:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with the test's running loop."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")


def _constraint_name(error: IntegrityError) -> str | None:
    """The violated constraint BY NAME, never by message text."""
    return getattr(error.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with migrated_head_database(_DB_NAME) as url:
        yield url


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()


@pytest.fixture
def throwaway_db_factory() -> Iterator[Callable[[str], str]]:
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_head_database(f"{_THROWAWAY_DB_PREFIX}_{suffix}")
        )


async def _insert(conn: AsyncConnection, email: str) -> None:
    await conn.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email)"),
        {"id": uuid4(), "email": email},
    )


async def _columns(conn: AsyncConnection) -> dict[str, tuple[str, str]]:
    rows = await conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'users'"
        )
    )
    return {name: (kind, nullable) for name, kind, nullable in rows}


async def test_the_table_holds_an_id_an_email_and_two_timestamps(conn: AsyncConnection) -> None:
    assert await _columns(conn) == {
        "id": ("uuid", "NO"),
        "email": ("text", "NO"),
        "created_at": ("timestamp with time zone", "NO"),
        "last_seen_at": ("timestamp with time zone", "NO"),
    }


async def test_both_timestamps_default_to_now(conn: AsyncConnection) -> None:
    await _insert(conn, "defaults@example.com")

    row = (
        await conn.execute(
            text(
                "SELECT created_at = now() AND last_seen_at = now() FROM users "
                "WHERE email = 'defaults@example.com'"
            )
        )
    ).scalar_one()

    assert row is True


async def test_one_address_is_one_user(conn: AsyncConnection) -> None:
    await _insert(conn, "twice@example.com")

    with pytest.raises(IntegrityError) as caught:
        await _insert(conn, "twice@example.com")

    assert _constraint_name(caught.value) == _EMAIL_UNIQUE


@pytest.mark.parametrize(
    "email", ["Upper@example.com", " padded@example.com", "tail@example.com ", "\ttab@example.com"]
)
async def test_only_the_normal_spelling_is_stored(conn: AsyncConnection, email: str) -> None:
    """The application folds case and whitespace (``normalize_email``); the
    database refuses anything else, so a second spelling of one address can
    never become a second user through some other writer."""
    with pytest.raises(IntegrityError) as caught:
        await _insert(conn, email)

    assert _constraint_name(caught.value) == _EMAIL_LOWER


def test_downgrade_drops_the_table(throwaway_db_factory: Callable[[str], str]) -> None:
    url = throwaway_db_factory("downgrade")

    _run_alembic_ok(url, "downgrade", "0028")

    async def exists() -> bool:
        engine = create_async_engine(url, pool_pre_ping=True)
        try:
            async with engine.connect() as connection:
                found = await connection.execute(text("SELECT to_regclass('users') IS NOT NULL"))
                return bool(found.scalar_one())
        finally:
            await engine.dispose()

    assert asyncio.run(exists()) is False

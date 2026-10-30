"""Migration ``0034`` -- the last four characters of each strategy's webhook secret
(multi-user design decision 25; tasks.md H.1).

* ``strategies.webhook_secret_last4`` is the last four characters of the setting's
  secret for every existing strategy, computed in Python as 0033 computed the hash,
  so the secret never enters SQL text and no message names it.
* It is NOT NULL, with a CHECK on four characters.
* It refuses, naming nothing secret, when strategies exist and the setting is
  shorter than four characters.

Real PostgreSQL. Each migration scenario seeds a database at ``0033`` and upgrades
it, so each has its own throwaway database; the constraint tests share one
module-scoped database and roll back. The subprocess gets ``WEBHOOK_SECRET``
explicitly, so no test depends on the developer's ``.env``.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_PREFIX = "strategy_manager_test_last4"

_SECRET = "wh-test-0034-Zq9X"
_LAST4 = "Zq9X"
_CHECK = "ck_strategies_webhook_secret_last4_length"
_COLUMN = "webhook_secret_last4"


def _alembic(
    database_url: str, *args: str, secret: str = _SECRET
) -> subprocess.CompletedProcess[str]:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with a running loop."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url, "WEBHOOK_SECRET": secret},
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_ok(database_url: str, *args: str, secret: str = _SECRET) -> None:
    result = _alembic(database_url, *args, secret=secret)
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


def _scalar(database_url: str, sql: str, params: dict[str, Any] | None = None) -> Any:
    return _query(database_url, sql, params)[0][0]


def _constraint_name(error: DBAPIError) -> str | None:
    """The violated constraint BY NAME, never by message text."""
    return getattr(error.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _version(database_url: str) -> str:
    return str(_scalar(database_url, "SELECT version_num FROM alembic_version"))


def _columns(database_url: str) -> set[str]:
    return {
        str(row[0])
        for row in _query(
            database_url,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'strategies'",
        )
    }


def _constraints(database_url: str) -> set[str]:
    return {
        str(row[0])
        for row in _query(
            database_url,
            "SELECT conname FROM pg_constraint WHERE conrelid = 'strategies'::regclass",
        )
    }


def _add_user(database_url: str, email: str) -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email) VALUES (:id, :email)",
        {"id": user_id, "email": email},
    )
    return user_id


def _add_strategy(database_url: str, author: UUID, name: str) -> UUID:
    strategy_id = uuid4()
    _query(
        database_url,
        "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
        "fill_mode, webhook_secret_hash) "
        "VALUES (:id, :author, :name, 'binance', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash')",
        {"id": strategy_id, "author": author, "name": name},
    )
    return strategy_id


@pytest.fixture
def at_0033() -> Iterator[Callable[[str], str]]:
    """A fresh database at ``0033`` per call, dropped at teardown."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_database(f"{_DB_PREFIX}_{suffix}", "0033")
        )


class Seeded:
    def __init__(self, url: str) -> None:
        self.url = url
        self.owner = _add_user(url, "owner@example.com")
        self.first = _add_strategy(url, self.owner, "first")
        self.second = _add_strategy(url, self.owner, "second")


@pytest.fixture(scope="module")
def seeded() -> Iterator[Seeded]:
    """Seeded at ``0033``, then upgraded: shared, read-mostly."""
    with migrated_database(f"{_DB_PREFIX}_seeded", "0033") as url:
        data = Seeded(url)
        _alembic_ok(url, "upgrade", "0034")
        yield data


@pytest.fixture
async def conn(seeded: Seeded) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(seeded.url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()


async def _insert_strategy(
    conn: AsyncConnection, author: UUID, name: str, *, last4: str | None
) -> None:
    columns = "id, author_id, name, exchange, venue, settlement_currency, fill_mode"
    columns += ", webhook_secret_hash"
    values = ":id, :author, :name, 'binance', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash'"
    params: dict[str, Any] = {"id": uuid4(), "author": author, "name": name}
    if last4 is not None:
        columns += f", {_COLUMN}"
        values += ", :last4"
        params["last4"] = last4
    await conn.execute(text(f"INSERT INTO strategies ({columns}) VALUES ({values})"), params)


# --- the backfill -----------------------------------------------------------


def test_every_strategy_gets_the_last_four_of_the_settings_secret(seeded: Seeded) -> None:
    rows = _query(seeded.url, f"SELECT name, {_COLUMN} FROM strategies ORDER BY name")

    assert rows == [("first", _LAST4), ("second", _LAST4)]


def test_the_secret_itself_is_stored_nowhere(seeded: Seeded) -> None:
    row = _query(seeded.url, "SELECT strategies::text FROM strategies WHERE name = 'first'")[0][0]

    assert _SECRET not in row


def test_the_column_is_not_null(seeded: Seeded) -> None:
    nullable = _scalar(
        seeded.url,
        "SELECT is_nullable FROM information_schema.columns "
        f"WHERE table_name = 'strategies' AND column_name = '{_COLUMN}'",
    )

    assert nullable == "NO"


def test_the_upgrade_logs_no_character_of_the_secret(at_0033: Callable[[str], str]) -> None:
    url = at_0033("logs")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")

    result = _alembic(url, "upgrade", "0034")

    assert result.returncode == 0
    said = result.stdout + result.stderr
    assert _LAST4 not in said
    assert _SECRET not in said


# --- the refusals -----------------------------------------------------------


def test_refuses_when_strategies_exist_and_the_secret_is_empty(
    at_0033: Callable[[str], str],
) -> None:
    url = at_0033("empty_secret")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")

    result = _alembic(url, "upgrade", "0034", secret="")

    assert result.returncode != 0
    assert "WEBHOOK_SECRET" in result.stderr
    assert _version(url) == "0033"
    assert _COLUMN not in _columns(url)


def test_refuses_when_strategies_exist_and_the_secret_is_shorter_than_four(
    at_0033: Callable[[str], str],
) -> None:
    url = at_0033("short_secret")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")

    result = _alembic(url, "upgrade", "0034", secret="xq7")

    assert result.returncode != 0
    assert "WEBHOOK_SECRET" in result.stderr
    assert "xq7" not in result.stdout + result.stderr
    assert _version(url) == "0033"
    assert _COLUMN not in _columns(url)


def test_an_empty_database_migrates_with_an_empty_secret(at_0033: Callable[[str], str]) -> None:
    url = at_0033("empty_database")

    _alembic_ok(url, "upgrade", "0034", secret="")

    assert _version(url) == "0034"
    assert _COLUMN in _columns(url)


def test_an_empty_database_migrates_with_a_short_secret(at_0033: Callable[[str], str]) -> None:
    url = at_0033("empty_database_short")

    _alembic_ok(url, "upgrade", "0034", secret="xq7")

    assert _version(url) == "0034"


# --- the constraints --------------------------------------------------------


async def test_a_strategy_without_the_last_four_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_strategy(conn, seeded.owner, "unmasked", last4=None)

    cause = caught.value.orig.__cause__  # type: ignore[union-attr]
    assert getattr(cause, "sqlstate", None) == "23502"
    assert getattr(cause, "column_name", None) == _COLUMN


@pytest.mark.parametrize("wrong", ["", "abc", "abcde"])
async def test_a_value_that_is_not_four_characters_is_refused(
    conn: AsyncConnection, seeded: Seeded, wrong: str
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_strategy(conn, seeded.owner, "odd", last4=wrong)

    assert _constraint_name(caught.value) == _CHECK


async def test_four_characters_are_accepted(conn: AsyncConnection, seeded: Seeded) -> None:
    await _insert_strategy(conn, seeded.owner, "masked", last4="ab_-")

    row = await conn.execute(
        text(f"SELECT {_COLUMN} FROM strategies WHERE name = 'masked'")
    )
    assert row.scalar_one() == "ab_-"


# --- downgrade --------------------------------------------------------------


def test_downgrade_drops_the_column_and_the_upgrade_runs_again(
    at_0033: Callable[[str], str],
) -> None:
    url = at_0033("downgrade")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")
    _alembic_ok(url, "upgrade", "0034")

    _alembic_ok(url, "downgrade", "0033")

    assert _version(url) == "0033"
    assert _COLUMN not in _columns(url)
    assert _CHECK not in _constraints(url)

    _alembic_ok(url, "upgrade", "0034")
    assert _version(url) == "0034"
    assert _query(url, f"SELECT {_COLUMN} FROM strategies") == [(_LAST4,)]

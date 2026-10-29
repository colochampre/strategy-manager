"""Migration ``0033`` -- the strategy's own secret, visibility and per-author name
(multi-user design AD6, decisions 21 and 23; tasks.md D.1).

* ``webhook_secret_hash`` is the SHA-256 hex of the setting's secret for every
  existing strategy, so today's alerts keep working. It is nullable here.
* ``visibility`` is ``PRIVATE`` for every existing strategy.
* ``strategies.name`` is unique per author, not across users.
* ``strategies.allocation_percent`` and its CHECK are gone: the share lives on
  the subscription.

Real PostgreSQL. Each migration scenario seeds a database at ``0032`` and
upgrades it, so each has its own throwaway database; the constraint tests share
one module-scoped database and roll back. The subprocess gets ``WEBHOOK_SECRET``
explicitly, so no test depends on the developer's ``.env``.
"""

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_PREFIX = "strategy_manager_test_authoring"

_SECRET = "wh-test-0033"
_VISIBILITY = "ck_strategies_visibility"
_AUTHOR_NAME = "ux_strategies_author_name"
_SHARE_RANGE = "ck_strategies_allocation_percent_range"


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


def _name_uniques(database_url: str) -> list[tuple[Any, ...]]:
    """Unique constraints of ``strategies`` with the column names they cover."""
    return _query(
        database_url,
        "SELECT c.conname, array_agg(a.attname::text ORDER BY a.attname) "
        "FROM pg_constraint AS c JOIN pg_attribute AS a "
        "ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.conrelid = 'strategies'::regclass AND c.contype = 'u' "
        "GROUP BY c.conname ORDER BY c.conname",
    )


def _add_user(database_url: str, email: str) -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email) VALUES (:id, :email)",
        {"id": user_id, "email": email},
    )
    return user_id


def _add_pool(database_url: str, user_id: UUID) -> int:
    return int(
        _scalar(
            database_url,
            "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
            "min_order_size) VALUES (:u, 'binance', 'usdt-m', 'USDT', 5) RETURNING id",
            {"u": user_id},
        )
    )


def _add_strategy(
    database_url: str, author: UUID, name: str, *, share: str | None = "30"
) -> UUID:
    strategy_id = uuid4()
    _query(
        database_url,
        "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
        "fill_mode, allocation_percent) "
        "VALUES (:id, :author, :name, 'binance', 'usdt-m', 'USDT', 'PARTIAL', :share)",
        {
            "id": strategy_id,
            "author": author,
            "name": name,
            "share": None if share is None else Decimal(share),
        },
    )
    return strategy_id


def _subscribe(
    database_url: str,
    user_id: UUID,
    strategy_id: UUID,
    pool_id: int,
    share: str,
    *,
    created_days: int = 0,
    status: str = "ACTIVE",
) -> None:
    _query(
        database_url,
        "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent, "
        "status, created_at) VALUES (gen_random_uuid(), :u, :s, :p, :share, :status, "
        "now() + make_interval(days => :days))",
        {
            "u": user_id,
            "s": strategy_id,
            "p": pool_id,
            "share": Decimal(share),
            "status": status,
            "days": created_days,
        },
    )


@pytest.fixture
def at_0032() -> Iterator[Callable[[str], str]]:
    """A fresh database at ``0032`` per call, dropped at teardown."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_database(f"{_DB_PREFIX}_{suffix}", "0032")
        )


class Seeded:
    def __init__(self, url: str) -> None:
        self.url = url
        self.owner = _add_user(url, "owner@example.com")
        self.other = _add_user(url, "other@example.com")
        self.first = _add_strategy(url, self.owner, "first")
        self.second = _add_strategy(url, self.owner, "second")


@pytest.fixture(scope="module")
def seeded() -> Iterator[Seeded]:
    """Seeded at ``0032``, then upgraded: shared, read-mostly."""
    with migrated_database(f"{_DB_PREFIX}_seeded", "0032") as url:
        data = Seeded(url)
        _alembic_ok(url, "upgrade", "0033")
        yield data


@pytest.fixture
async def conn(seeded: Seeded) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(seeded.url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()


async def _insert_strategy(
    conn: AsyncConnection, author: UUID, name: str, *, visibility: str | None = None
) -> None:
    columns = "id, author_id, name, exchange, venue, settlement_currency, fill_mode"
    values = ":id, :author, :name, 'binance', 'usdt-m', 'USDT', 'PARTIAL'"
    params: dict[str, Any] = {"id": uuid4(), "author": author, "name": name}
    if visibility is not None:
        columns += ", visibility"
        values += ", :visibility"
        params["visibility"] = visibility
    await conn.execute(text(f"INSERT INTO strategies ({columns}) VALUES ({values})"), params)


# --- the backfill -----------------------------------------------------------


def test_every_strategy_gets_the_hash_of_the_settings_secret(seeded: Seeded) -> None:
    hashes = _query(seeded.url, "SELECT name, webhook_secret_hash FROM strategies ORDER BY name")

    expected = hashlib.sha256(_SECRET.encode("utf-8")).hexdigest()
    assert hashes == [("first", expected), ("second", expected)]


def test_the_secret_itself_is_stored_nowhere(seeded: Seeded) -> None:
    row = _query(seeded.url, "SELECT strategies::text FROM strategies WHERE name = 'first'")[0][0]

    assert _SECRET not in row


def test_the_hash_column_is_nullable(seeded: Seeded) -> None:
    nullable = _scalar(
        seeded.url,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'strategies' AND column_name = 'webhook_secret_hash'",
    )

    assert nullable == "YES"


def test_existing_strategies_are_private(seeded: Seeded) -> None:
    rows = _query(seeded.url, "SELECT DISTINCT visibility FROM strategies")

    assert rows == [("PRIVATE",)]


def test_the_share_column_and_its_check_are_gone(seeded: Seeded) -> None:
    assert "allocation_percent" not in _columns(seeded.url)
    assert _SHARE_RANGE not in _constraints(seeded.url)


def test_the_global_name_unique_is_replaced_by_the_per_author_one(seeded: Seeded) -> None:
    assert _name_uniques(seeded.url) == [(_AUTHOR_NAME, ["author_id", "name"])]


def test_refuses_when_strategies_exist_and_the_secret_is_empty(
    at_0032: Callable[[str], str],
) -> None:
    url = at_0032("empty_secret")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")

    result = _alembic(url, "upgrade", "0033", secret="")

    assert result.returncode != 0
    assert "WEBHOOK_SECRET" in result.stderr
    assert _version(url) == "0032"
    assert "webhook_secret_hash" not in _columns(url)
    assert "allocation_percent" in _columns(url)


def test_an_empty_database_migrates_with_an_empty_secret(at_0032: Callable[[str], str]) -> None:
    url = at_0032("empty_database")

    _alembic_ok(url, "upgrade", "0033", secret="")

    assert _version(url) == "0033"
    assert "webhook_secret_hash" in _columns(url)


# --- the constraints --------------------------------------------------------


async def test_visibility_defaults_to_private(conn: AsyncConnection, seeded: Seeded) -> None:
    await _insert_strategy(conn, seeded.owner, "defaulted")

    row = await conn.execute(text("SELECT visibility FROM strategies WHERE name = 'defaulted'"))
    assert row.scalar_one() == "PRIVATE"


async def test_a_public_strategy_is_accepted(conn: AsyncConnection, seeded: Seeded) -> None:
    await _insert_strategy(conn, seeded.owner, "open", visibility="PUBLIC")

    row = await conn.execute(text("SELECT visibility FROM strategies WHERE name = 'open'"))
    assert row.scalar_one() == "PUBLIC"


async def test_an_unknown_visibility_is_refused(conn: AsyncConnection, seeded: Seeded) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_strategy(conn, seeded.owner, "odd", visibility="SECRET")

    assert _constraint_name(caught.value) == _VISIBILITY


async def test_two_authors_may_share_a_name(conn: AsyncConnection, seeded: Seeded) -> None:
    await _insert_strategy(conn, seeded.other, "first")

    count = await conn.execute(text("SELECT count(*) FROM strategies WHERE name = 'first'"))
    assert count.scalar_one() == 2


async def test_one_author_may_not_repeat_a_name(conn: AsyncConnection, seeded: Seeded) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_strategy(conn, seeded.owner, "first")

    assert _constraint_name(caught.value) == _AUTHOR_NAME


# --- downgrade --------------------------------------------------------------


def test_downgrade_restores_each_share_from_the_latest_author_subscription_and_upgrades_again(
    at_0032: Callable[[str], str],
) -> None:
    url = at_0032("downgrade")
    owner = _add_user(url, "owner@example.com")
    pool = _add_pool(url, owner)
    live = _add_strategy(url, owner, "live", share=None)
    older = _add_strategy(url, owner, "older", share=None)
    _subscribe(url, owner, live, pool, "30", created_days=-2, status="ENDED")
    _subscribe(url, owner, live, pool, "45", created_days=-1)
    _subscribe(url, owner, older, pool, "7")
    _alembic_ok(url, "upgrade", "0033")

    _alembic_ok(url, "downgrade", "0032")

    assert _version(url) == "0032"
    assert _query(url, "SELECT name, allocation_percent FROM strategies ORDER BY name") == [
        ("live", Decimal("45")),
        ("older", Decimal("7")),
    ]
    assert "webhook_secret_hash" not in _columns(url)
    assert "visibility" not in _columns(url)
    assert _SHARE_RANGE in _constraints(url)
    assert _AUTHOR_NAME not in _constraints(url)
    uniques = _name_uniques(url)
    assert [columns for _, columns in uniques] == [["name"]]

    _alembic_ok(url, "upgrade", "0033")
    assert _version(url) == "0033"
    assert _name_uniques(url) == [(_AUTHOR_NAME, ["author_id", "name"])]


def test_the_downgraded_share_column_is_nullable(at_0032: Callable[[str], str]) -> None:
    url = at_0032("downgrade_nullable")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")
    _alembic_ok(url, "upgrade", "0033")

    _alembic_ok(url, "downgrade", "0032")

    nullable = _scalar(
        url,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'strategies' AND column_name = 'allocation_percent'",
    )
    assert nullable == "YES"


def test_downgrade_refuses_once_a_second_user_exists(at_0032: Callable[[str], str]) -> None:
    url = at_0032("downgrade_two_users")
    owner = _add_user(url, "owner@example.com")
    _add_strategy(url, owner, "live")
    _alembic_ok(url, "upgrade", "0033")
    _add_user(url, "other@example.com")

    result = _alembic(url, "downgrade", "0032")

    assert result.returncode != 0
    assert "found 2" in result.stderr
    assert _version(url) == "0033"

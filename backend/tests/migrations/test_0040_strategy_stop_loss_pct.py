"""Migration ``0040`` -- a strategy's stop level (subscriber-safety D5 and D6;
tasks.md SS.3).

* ``strategies.stop_loss_pct`` is ``NUMERIC(4, 2)``, ``NOT NULL``, from 1 to 50.
  Every strategy that exists gets 10; a row written without one gets 10 too.
* The downgrade removes the column and its CHECK and leaves every other column
  as it was.

Real PostgreSQL, one database per scenario, seeded at ``0039``.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from decimal import Decimal
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
_DB_NAME = "strategy_manager_test_stop_loss_pct"
_CHECK = "ck_strategies_stop_loss_pct_range"
_COLUMNS = "id, author_id, name, exchange, venue, fill_mode, enabled, visibility, description"


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


def _violated(database_url: str, sql: str, params: dict[str, Any]) -> str | None:
    """The constraint a write trips, BY NAME, never by message text."""
    with pytest.raises(DBAPIError) as caught:
        _query(database_url, sql, params)
    return getattr(caught.value.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _has_column(database_url: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'strategies' AND column_name = 'stop_loss_pct'",
        )
    )


class World:
    """One user and the strategies written at ``0039``."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.user = uuid4()
        _query(
            url,
            "INSERT INTO users (id, email) VALUES (:id, 'owner@example.com')",
            {"id": self.user},
        )

    def strategy(self, name: str) -> UUID:
        strategy = uuid4()
        _query(
            self.url,
            "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
            "fill_mode, webhook_secret_hash, webhook_secret_last4) VALUES (:id, :u, :n, "
            "'binance', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash', 'fxtr')",
            {"id": strategy, "u": self.user, "n": name},
        )
        return strategy

    def level(self, strategy: UUID) -> Decimal:
        value = _query(
            self.url, "SELECT stop_loss_pct FROM strategies WHERE id = :id", {"id": strategy}
        )[0][0]
        assert isinstance(value, Decimal)
        return value


@pytest.fixture
def at_0039() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0039") as url:
        yield url


def test_every_existing_strategy_gets_ten_and_nothing_else_changes(at_0039: str) -> None:
    world = World(at_0039)
    first = world.strategy("first")
    second = world.strategy("second")
    before = _query(at_0039, f"SELECT {_COLUMNS} FROM strategies ORDER BY id")

    _alembic(at_0039, "upgrade", "0040")

    assert (world.level(first), world.level(second)) == (Decimal("10"), Decimal("10"))
    assert _query(at_0039, f"SELECT {_COLUMNS} FROM strategies ORDER BY id") == before


def test_a_strategy_written_without_a_level_gets_ten(at_0039: str) -> None:
    world = World(at_0039)
    _alembic(at_0039, "upgrade", "0040")

    assert world.level(world.strategy("later")) == Decimal("10")


@pytest.mark.parametrize("level", ["0.5", "0", "-1", "0.99", "50.01", "60"])
def test_the_check_refuses_a_level_out_of_range(at_0039: str, level: str) -> None:
    world = World(at_0039)
    strategy = world.strategy("first")
    _alembic(at_0039, "upgrade", "0040")

    assert (
        _violated(
            at_0039,
            "UPDATE strategies SET stop_loss_pct = :l WHERE id = :id",
            {"l": Decimal(level), "id": strategy},
        )
        == _CHECK
    )
    assert world.level(strategy) == Decimal("10")


@pytest.mark.parametrize("level", ["1", "7.5", "12.34", "50"])
def test_the_check_takes_a_level_from_one_to_fifty(at_0039: str, level: str) -> None:
    world = World(at_0039)
    strategy = world.strategy("first")
    _alembic(at_0039, "upgrade", "0040")

    _query(
        at_0039,
        "UPDATE strategies SET stop_loss_pct = :l WHERE id = :id",
        {"l": Decimal(level), "id": strategy},
    )

    assert world.level(strategy) == Decimal(level)


def test_a_level_cannot_be_null(at_0039: str) -> None:
    world = World(at_0039)
    strategy = world.strategy("first")
    _alembic(at_0039, "upgrade", "0040")

    with pytest.raises(DBAPIError) as caught:
        _query(
            at_0039,
            "UPDATE strategies SET stop_loss_pct = NULL WHERE id = :id",
            {"id": strategy},
        )
    assert getattr(caught.value.orig.__cause__, "sqlstate", None) == "23502"  # type: ignore[union-attr]


def test_downgrade_removes_the_column_and_the_upgrade_runs_again(at_0039: str) -> None:
    world = World(at_0039)
    strategy = world.strategy("first")
    before = _query(at_0039, f"SELECT {_COLUMNS} FROM strategies")
    _alembic(at_0039, "upgrade", "0040")
    _query(
        at_0039,
        "UPDATE strategies SET stop_loss_pct = 7.5 WHERE id = :id",
        {"id": strategy},
    )

    _alembic(at_0039, "downgrade", "0039")

    assert not _has_column(at_0039)
    assert _query(at_0039, "SELECT 1 FROM pg_constraint WHERE conname = :n", {"n": _CHECK}) == []
    assert _query(at_0039, f"SELECT {_COLUMNS} FROM strategies") == before

    _alembic(at_0039, "upgrade", "0040")

    assert world.level(strategy) == Decimal("10")

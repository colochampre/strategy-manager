"""Migration ``0037`` -- a subscription's leverage and a strategy's description
(multi-user decisions 38 and 39; tasks.md H.1).

* ``subscriptions.leverage`` is an integer from 1 to 125, ``NOT NULL``. Every
  subscription that exists gets 2, the owner's stated default; a row written
  without one gets 1, where every new seat starts.
* ``strategies.description`` is optional text, trimmed, of 1 to 2,000
  characters. Nothing is backfilled.
* The downgrade removes both and leaves every other column as it was.

Real PostgreSQL, one database per scenario, seeded at ``0036``.
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
_DB_NAME = "strategy_manager_test_leverage"
_LEVERAGE_CHECK = "ck_subscriptions_leverage_range"
_DESCRIPTION_CHECK = "ck_strategies_description_shape"
_SUBSCRIPTION_COLUMNS = (
    "id, user_id, strategy_id, pool_id, allocation_percent, status, created_at, "
    "left_at, ended_at"
)


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


def _has_column(database_url: str, table: str, column: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c",
            {"t": table, "c": column},
        )
    )


class World:
    """One user with a pool and a strategy at ``0036``."""

    def __init__(self, url: str, email: str = "owner@example.com") -> None:
        self.url = url
        self.user = uuid4()
        _query(url, "INSERT INTO users (id, email) VALUES (:id, :e)", {"id": self.user, "e": email})
        self.pool = int(
            _query(
                url,
                "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
                "min_order_size) VALUES (:u, 'binance', 'usdt-m', 'USDT', 5) RETURNING id",
                {"u": self.user},
            )[0][0]
        )

    def strategy(self, name: str = "first") -> UUID:
        strategy = uuid4()
        _query(
            self.url,
            "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
            "fill_mode, webhook_secret_hash, webhook_secret_last4) VALUES (:id, :u, :n, "
            "'binance', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash', 'fxtr')",
            {"id": strategy, "u": self.user, "n": name},
        )
        return strategy

    def subscription(self, strategy: UUID, *, status: str = "ACTIVE") -> UUID:
        subscription = uuid4()
        _query(
            self.url,
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent, "
            "status, ended_at) VALUES (:id, :u, :s, :p, 20, :status, "
            "CASE WHEN :status = 'ENDED' THEN now() END)",
            {
                "id": subscription,
                "u": self.user,
                "s": strategy,
                "p": self.pool,
                "status": status,
            },
        )
        return subscription

    def leverage(self, subscription: UUID) -> Any:
        return _query(
            self.url, "SELECT leverage FROM subscriptions WHERE id = :id", {"id": subscription}
        )[0][0]


@pytest.fixture
def at_0036() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0036") as url:
        yield url


def test_every_existing_subscription_gets_two_and_nothing_else_changes(at_0036: str) -> None:
    world = World(at_0036)
    live = world.subscription(world.strategy("first"))
    ended = world.subscription(world.strategy("second"), status="ENDED")
    before = _query(at_0036, f"SELECT {_SUBSCRIPTION_COLUMNS} FROM subscriptions ORDER BY id")

    _alembic(at_0036, "upgrade", "0037")

    assert (world.leverage(live), world.leverage(ended)) == (2, 2)
    assert (
        _query(at_0036, f"SELECT {_SUBSCRIPTION_COLUMNS} FROM subscriptions ORDER BY id")
        == before
    )


def test_a_subscription_written_without_a_leverage_gets_one(at_0036: str) -> None:
    world = World(at_0036)
    strategy = world.strategy()
    _alembic(at_0036, "upgrade", "0037")

    assert world.leverage(world.subscription(strategy)) == 1


@pytest.mark.parametrize("leverage", [0, -1, 126])
def test_the_check_refuses_a_leverage_out_of_range(at_0036: str, leverage: int) -> None:
    world = World(at_0036)
    subscription = world.subscription(world.strategy())
    _alembic(at_0036, "upgrade", "0037")

    assert (
        _violated(
            at_0036,
            "UPDATE subscriptions SET leverage = :l WHERE id = :id",
            {"l": leverage, "id": subscription},
        )
        == _LEVERAGE_CHECK
    )


def test_the_check_takes_one_and_one_hundred_twenty_five(at_0036: str) -> None:
    world = World(at_0036)
    subscription = world.subscription(world.strategy())
    _alembic(at_0036, "upgrade", "0037")

    for leverage in (1, 125):
        _query(
            at_0036,
            "UPDATE subscriptions SET leverage = :l WHERE id = :id",
            {"l": leverage, "id": subscription},
        )
        assert world.leverage(subscription) == leverage


def test_a_leverage_cannot_be_null(at_0036: str) -> None:
    world = World(at_0036)
    subscription = world.subscription(world.strategy())
    _alembic(at_0036, "upgrade", "0037")

    with pytest.raises(DBAPIError) as caught:
        _query(
            at_0036,
            "UPDATE subscriptions SET leverage = NULL WHERE id = :id",
            {"id": subscription},
        )
    assert getattr(caught.value.orig.__cause__, "sqlstate", None) == "23502"  # type: ignore[union-attr]


def test_no_strategy_gets_a_description(at_0036: str) -> None:
    world = World(at_0036)
    world.strategy("first")
    world.strategy("second")

    _alembic(at_0036, "upgrade", "0037")

    assert _query(at_0036, "SELECT count(*) FROM strategies WHERE description IS NULL") == [(2,)]


@pytest.mark.parametrize(
    "description",
    ["", " Trend", "Trend ", "Trend\n", "\tTrend", "x" * 2001],
    ids=["empty", "lead", "trail", "trail-newline", "lead-tab", "long"],
)
def test_the_check_refuses_a_description_the_domain_refuses(
    at_0036: str, description: str
) -> None:
    world = World(at_0036)
    strategy = world.strategy()
    _alembic(at_0036, "upgrade", "0037")

    assert (
        _violated(
            at_0036,
            "UPDATE strategies SET description = :d WHERE id = :id",
            {"d": description, "id": strategy},
        )
        == _DESCRIPTION_CHECK
    )


@pytest.mark.parametrize("description", ["x", "x" * 2000, "Trend.\n\nx2 recommended."])
def test_the_check_takes_a_trimmed_description_up_to_two_thousand(
    at_0036: str, description: str
) -> None:
    world = World(at_0036)
    strategy = world.strategy()
    _alembic(at_0036, "upgrade", "0037")

    _query(
        at_0036,
        "UPDATE strategies SET description = :d WHERE id = :id",
        {"d": description, "id": strategy},
    )

    assert _query(at_0036, "SELECT description FROM strategies") == [(description,)]


def test_downgrade_removes_both_and_the_upgrade_runs_again(at_0036: str) -> None:
    world = World(at_0036)
    strategy = world.strategy()
    subscription = world.subscription(strategy)
    _alembic(at_0036, "upgrade", "0037")
    _query(
        at_0036,
        "UPDATE strategies SET description = 'Trend.' WHERE id = :id",
        {"id": strategy},
    )

    _alembic(at_0036, "downgrade", "0036")

    assert not _has_column(at_0036, "subscriptions", "leverage")
    assert not _has_column(at_0036, "strategies", "description")
    for check in (_LEVERAGE_CHECK, _DESCRIPTION_CHECK):
        assert _query(at_0036, "SELECT 1 FROM pg_constraint WHERE conname = :n", {"n": check}) == []
    assert _query(at_0036, "SELECT id FROM subscriptions") == [(subscription,)]

    _alembic(at_0036, "upgrade", "0037")

    assert world.leverage(subscription) == 2

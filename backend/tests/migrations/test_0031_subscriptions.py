"""Migration ``0031`` -- ``subscriptions`` (multi-user design AD3; tasks.md C.1).

A subscription is the only way to trade a strategy, the author included. The
migration gives every existing strategy its author's subscription, in the
author's pool for the strategy's market, at the strategy's share: ACTIVE while
the strategy is not archived, ENDED (``ended_at = archived_at``) once it is.
With no such pool it refuses and names the strategy.

The database itself refuses a subscription in another user's pool (composite
FK) and one whose pool trades another market than its strategy (trigger).

Real PostgreSQL. Each migration scenario seeds a database at ``0030`` and
upgrades it, so each has its own throwaway database; the constraint tests share
one module-scoped database and roll back.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime
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
_DB_PREFIX = "strategy_manager_test_subscriptions"

_POOL_FK = "fk_subscriptions_pool"
_LIVE_UNIQUE = "ux_subscriptions_one_live_per_strategy"
_MARKET_MATCH = "ck_subscriptions_pool_market"
_SHARE_RANGE = "ck_subscriptions_allocation_percent_range"
_STATUS = "ck_subscriptions_status"
_STRATEGY_SHARE_RANGE = "ck_strategies_allocation_percent_range"

_ARCHIVED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with a running loop."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_ok(database_url: str, *args: str) -> None:
    result = _alembic(database_url, *args)
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


def _add_user(database_url: str, email: str) -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email) VALUES (:id, :email)",
        {"id": user_id, "email": email},
    )
    return user_id


def _add_pool(database_url: str, user_id: UUID, exchange: str, venue: str) -> int:
    return int(
        _scalar(
            database_url,
            "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
            "min_order_size) VALUES (:u, :exchange, :venue, 'USDT', 5) RETURNING id",
            {"u": user_id, "exchange": exchange, "venue": venue},
        )
    )


def _add_strategy(
    database_url: str,
    author: UUID,
    name: str,
    *,
    exchange: str = "binance",
    venue: str = "usdt-m",
    share: str = "30",
    archived: bool = False,
) -> UUID:
    strategy_id = uuid4()
    _query(
        database_url,
        "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
        "fill_mode, allocation_percent, archived_at) "
        "VALUES (:id, :author, :name, :exchange, :venue, 'USDT', 'PARTIAL', :share, :archived)",
        {
            "id": strategy_id,
            "author": author,
            "name": name,
            "exchange": exchange,
            "venue": venue,
            "share": Decimal(share),
            "archived": _ARCHIVED_AT if archived else None,
        },
    )
    return strategy_id


@pytest.fixture
def at_0030() -> Iterator[Callable[[str], str]]:
    """A fresh database at ``0030`` per call, dropped at teardown."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_database(f"{_DB_PREFIX}_{suffix}", "0030")
        )


class Seeded:
    def __init__(self, url: str) -> None:
        self.url = url
        self.owner = _add_user(url, "owner@example.com")
        self.other = _add_user(url, "other@example.com")
        self.owner_pool = _add_pool(url, self.owner, "binance", "usdt-m")
        self.owner_bybit_pool = _add_pool(url, self.owner, "bybit", "usdt-m")
        self.other_pool = _add_pool(url, self.other, "binance", "usdt-m")
        self.live = _add_strategy(url, self.owner, "live", share="30")
        self.archived = _add_strategy(url, self.owner, "archived", share="5", archived=True)
        self.bybit = _add_strategy(url, self.owner, "bybit", exchange="bybit", share="10")


@pytest.fixture(scope="module")
def seeded() -> Iterator[Seeded]:
    """Seeded at ``0030``, then upgraded: shared, read-mostly."""
    with migrated_database(f"{_DB_PREFIX}_seeded", "0030") as url:
        data = Seeded(url)
        _alembic_ok(url, "upgrade", "0031")
        yield data


@pytest.fixture
async def conn(seeded: Seeded) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(seeded.url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()


# --- the backfill -----------------------------------------------------------


def test_every_strategy_gets_its_authors_subscription(seeded: Seeded) -> None:
    rows = _query(
        seeded.url,
        "SELECT s.name, sub.user_id, sub.pool_id, sub.allocation_percent, sub.status, "
        "sub.ended_at, sub.left_at FROM subscriptions sub "
        "JOIN strategies s ON s.id = sub.strategy_id ORDER BY s.name",
    )

    assert rows == [
        ("archived", seeded.owner, seeded.owner_pool, Decimal("5"), "ENDED", _ARCHIVED_AT, None),
        ("bybit", seeded.owner, seeded.owner_bybit_pool, Decimal("10"), "ACTIVE", None, None),
        ("live", seeded.owner, seeded.owner_pool, Decimal("30"), "ACTIVE", None, None),
    ]


def test_the_strategies_keep_their_share_but_it_may_now_be_null(seeded: Seeded) -> None:
    shares = _query(seeded.url, "SELECT name, allocation_percent FROM strategies ORDER BY name")
    nullable = _scalar(
        seeded.url,
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'strategies' AND column_name = 'allocation_percent'",
    )

    assert shares == [
        ("archived", Decimal("5")),
        ("bybit", Decimal("10")),
        ("live", Decimal("30")),
    ]
    assert nullable == "YES"


def test_an_empty_database_migrates(at_0030: Callable[[str], str]) -> None:
    url = at_0030("empty")

    _alembic_ok(url, "upgrade", "0031")

    assert _version(url) == "0031"
    assert _scalar(url, "SELECT count(*) FROM subscriptions") == 0


def test_refuses_a_strategy_whose_author_has_no_pool_for_its_market(
    at_0030: Callable[[str], str],
) -> None:
    url = at_0030("no_pool")
    owner = _add_user(url, "owner@example.com")
    _add_pool(url, owner, "bybit", "usdt-m")
    _add_strategy(url, owner, "orphaned-market")

    result = _alembic(url, "upgrade", "0031")

    assert result.returncode != 0
    assert "orphaned-market" in result.stderr
    assert "found 0" in result.stderr
    assert _version(url) == "0030"
    assert (
        _scalar(
            url,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'subscriptions'",
        )
        == 0
    )


def test_does_not_use_another_users_pool_for_the_backfill(
    at_0030: Callable[[str], str],
) -> None:
    url = at_0030("someone_elses_pool")
    owner = _add_user(url, "owner@example.com")
    other = _add_user(url, "other@example.com")
    _add_pool(url, other, "binance", "usdt-m")
    _add_strategy(url, owner, "mine")

    result = _alembic(url, "upgrade", "0031")

    assert result.returncode != 0
    assert "mine" in result.stderr


def test_the_backfill_picks_the_authors_pool_beside_another_users_on_the_same_market(
    at_0030: Callable[[str], str],
) -> None:
    url = at_0030("two_pools_one_market")
    owner = _add_user(url, "owner@example.com")
    other = _add_user(url, "other@example.com")
    _add_pool(url, other, "binance", "usdt-m")
    owners_pool = _add_pool(url, owner, "binance", "usdt-m")
    _add_strategy(url, owner, "mine")

    _alembic_ok(url, "upgrade", "0031")

    rows = _query(url, "SELECT user_id, pool_id FROM subscriptions")
    assert rows == [(owner, owners_pool)]


# --- the constraints --------------------------------------------------------


async def _subscribe(
    conn: AsyncConnection,
    user_id: UUID,
    strategy_id: UUID,
    pool_id: int,
    *,
    share: str = "20",
    status: str = "ACTIVE",
) -> None:
    await conn.execute(
        text(
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent, "
            "status) VALUES (:id, :user_id, :strategy_id, :pool_id, :share, :status)"
        ),
        {
            "id": uuid4(),
            "user_id": user_id,
            "strategy_id": strategy_id,
            "pool_id": pool_id,
            "share": Decimal(share),
            "status": status,
        },
    )


async def test_another_user_subscribes_to_the_same_strategy(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    await _subscribe(conn, seeded.other, seeded.live, seeded.other_pool)

    count = await conn.execute(
        text("SELECT count(*) FROM subscriptions WHERE strategy_id = :s"), {"s": seeded.live}
    )
    assert count.scalar_one() == 2


async def test_a_subscription_cannot_sit_in_another_users_pool(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _subscribe(conn, seeded.other, seeded.live, seeded.owner_pool)

    assert _constraint_name(caught.value) == _POOL_FK


async def test_a_second_live_subscription_to_a_strategy_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _subscribe(conn, seeded.owner, seeded.live, seeded.owner_pool)

    assert _constraint_name(caught.value) == _LIVE_UNIQUE


async def test_a_leaving_subscription_still_counts_as_live(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    await conn.execute(
        text("UPDATE subscriptions SET status = 'LEAVING' WHERE strategy_id = :s"),
        {"s": seeded.live},
    )

    with pytest.raises(IntegrityError) as caught:
        await _subscribe(conn, seeded.owner, seeded.live, seeded.owner_pool)

    assert _constraint_name(caught.value) == _LIVE_UNIQUE


async def test_a_user_subscribes_again_once_the_last_one_ended(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    await _subscribe(conn, seeded.owner, seeded.archived, seeded.owner_pool)

    count = await conn.execute(
        text("SELECT count(*) FROM subscriptions WHERE strategy_id = :s"),
        {"s": seeded.archived},
    )
    assert count.scalar_one() == 2


async def test_a_pool_on_another_market_than_the_strategy_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _subscribe(conn, seeded.other, seeded.bybit, seeded.other_pool)

    assert _constraint_name(caught.value) == _MARKET_MATCH
    assert "bybit" in str(caught.value)


async def test_moving_a_subscription_to_a_pool_on_another_market_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text("UPDATE subscriptions SET pool_id = :pool WHERE strategy_id = :s"),
            {"pool": seeded.owner_bybit_pool, "s": seeded.live},
        )

    assert _constraint_name(caught.value) == _MARKET_MATCH


async def test_pointing_a_subscription_at_a_strategy_on_another_market_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text("UPDATE subscriptions SET strategy_id = :new WHERE strategy_id = :old"),
            {"new": seeded.bybit, "old": seeded.live},
        )

    assert _constraint_name(caught.value) == _MARKET_MATCH


async def test_a_share_outside_the_range_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _subscribe(conn, seeded.other, seeded.live, seeded.other_pool, share="0")

    assert _constraint_name(caught.value) == _SHARE_RANGE


async def test_an_unknown_status_is_refused(conn: AsyncConnection, seeded: Seeded) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _subscribe(
            conn, seeded.other, seeded.live, seeded.other_pool, status="PAUSED"
        )

    assert _constraint_name(caught.value) == _STATUS


async def test_deleting_a_strategy_takes_its_subscriptions_and_nothing_else(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    await _subscribe(conn, seeded.other, seeded.live, seeded.other_pool)

    await conn.execute(text("DELETE FROM strategies WHERE id = :s"), {"s": seeded.live})

    rows = await conn.execute(text("SELECT strategy_id FROM subscriptions"))
    remaining = sorted(row.strategy_id for row in rows)
    assert remaining == sorted([seeded.archived, seeded.bybit])


async def test_a_strategy_keeps_its_share_range_check(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text("UPDATE strategies SET allocation_percent = 101 WHERE id = :s"),
            {"s": seeded.live},
        )

    assert _constraint_name(caught.value) == _STRATEGY_SHARE_RANGE


# --- downgrade --------------------------------------------------------------


def test_downgrade_copies_the_latest_share_back_and_upgrades_again(
    at_0030: Callable[[str], str],
) -> None:
    url = at_0030("downgrade")
    owner = _add_user(url, "owner@example.com")
    pool = _add_pool(url, owner, "binance", "usdt-m")
    _add_pool(url, owner, "bybit", "usdt-m")
    live = _add_strategy(url, owner, "live", share="30")
    _add_strategy(url, owner, "archived", share="5", archived=True)
    _add_strategy(url, owner, "bybit", exchange="bybit", share="10")
    _alembic_ok(url, "upgrade", "0031")
    # The strategy's own column is no longer read: a later subscription wins.
    _query(
        url,
        "UPDATE subscriptions SET allocation_percent = 12, status = 'ENDED', "
        "ended_at = now() WHERE strategy_id = :s",
        {"s": live},
    )
    _query(
        url,
        "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent, "
        "status, created_at) VALUES (gen_random_uuid(), :u, :s, :p, 45, 'ACTIVE', "
        "now() + interval '1 day')",
        {"u": owner, "s": live, "p": pool},
    )
    _query(url, "UPDATE strategies SET allocation_percent = NULL")

    _alembic_ok(url, "downgrade", "0030")

    assert _version(url) == "0030"
    assert _query(url, "SELECT name, allocation_percent FROM strategies ORDER BY name") == [
        ("archived", Decimal("5")),
        ("bybit", Decimal("10")),
        ("live", Decimal("45")),
    ]
    assert (
        _scalar(
            url,
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'strategies' AND column_name = 'allocation_percent'",
        )
        == "NO"
    )
    assert (
        _scalar(
            url,
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'subscriptions'",
        )
        == 0
    )
    assert (
        _scalar(
            url, "SELECT count(*) FROM pg_proc WHERE proname = 'subscriptions_pool_market_guard'"
        )
        == 0
    )

    _alembic_ok(url, "upgrade", "0031")
    assert _version(url) == "0031"
    assert _scalar(url, "SELECT count(*) FROM subscriptions") == 3


def test_downgrade_refuses_once_a_second_user_exists(at_0030: Callable[[str], str]) -> None:
    url = at_0030("downgrade_two_users")
    owner = _add_user(url, "owner@example.com")
    _add_pool(url, owner, "binance", "usdt-m")
    _add_strategy(url, owner, "live")
    _alembic_ok(url, "upgrade", "0031")
    _add_user(url, "other@example.com")

    result = _alembic(url, "downgrade", "0030")

    assert result.returncode != 0
    assert "found 2" in result.stderr
    assert _version(url) == "0031"


def test_downgrade_refuses_a_strategy_left_with_no_share_to_restore(
    at_0030: Callable[[str], str],
) -> None:
    url = at_0030("downgrade_no_share")
    owner = _add_user(url, "owner@example.com")
    _add_pool(url, owner, "binance", "usdt-m")
    _alembic_ok(url, "upgrade", "0031")
    # Created after the upgrade: it has a NULL share and no subscription.
    _query(
        url,
        "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
        "fill_mode, allocation_percent) VALUES (gen_random_uuid(), :u, 'shareless', 'binance', "
        "'usdt-m', 'USDT', 'PARTIAL', NULL)",
        {"u": owner},
    )

    result = _alembic(url, "downgrade", "0030")

    assert result.returncode != 0
    assert "shareless" in result.stderr
    assert _version(url) == "0031"

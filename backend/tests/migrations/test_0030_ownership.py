"""Migration ``0030`` -- every owned row gets its owner (multi-user design AD2;
tasks.md B.1).

The one user that exists when the migration runs owns every existing row: the
owner, who signed in once after PR A (decision 11). With rows to own and any
other number of users, the migration refuses rather than guess. A database
nobody has ever signed into holds nothing but the four pools ``0003`` seeded;
those are dropped, because saving a key creates its pool again.

The ledger is append-only, so its owner arrives as a constant default stored in
the catalogue: no row is rewritten, and each row keeps its ``xmin``.

Real PostgreSQL. Each scenario seeds a database at ``0029`` and upgrades it, so
each has its own throwaway database; the constraint tests share one module-scoped
database and roll back.
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_PREFIX = "strategy_manager_test_ownership"

_OWNED_TABLES = (
    "exchange_credentials",
    "capital_pools",
    "pool_balance_snapshots",
    "reservations",
    "execution_attempts",
    "ledger_entries",
    "reconciliation_discrepancies",
    "booking_proposals",
)
_POOL_REFERENCES = (
    "pool_balance_snapshots",
    "reservations",
    "reconciliation_discrepancies",
    "booking_proposals",
)
_POOL = {"exchange": "bybit", "venue": "usdt-m", "settlement_currency": "USDT"}
_POOL_OF_USER = (
    "SELECT id FROM capital_pools WHERE user_id = :u "
    "AND exchange = 'bybit' AND venue = 'usdt-m' AND settlement_currency = 'USDT'"
)

_ACTIVE_KEY = "ux_exchange_credentials_one_active_per_exchange"
_POOL_PER_USER = "ux_capital_pools_user_market"
_LEDGER_FILL = "ux_ledger_exchange_fill"
_OPEN_DISCREPANCY = "ux_reconciliation_open_per_symbol"
_RESERVATION_POOL = "fk_reservations_capital_pool"
_STRATEGY_VENUE = "ck_strategies_venue"


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


def _constraint_name(error: IntegrityError) -> str | None:
    """The violated constraint BY NAME, never by message text."""
    return getattr(error.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]


def _add_user(database_url: str, email: str) -> UUID:
    user_id = uuid4()
    _query(
        database_url,
        "INSERT INTO users (id, email) VALUES (:id, :email)",
        {"id": user_id, "email": email},
    )
    return user_id


def _seed_owned_rows(database_url: str) -> dict[str, UUID]:
    """One row in every owned table, written as code at ``0029`` writes them.
    The pool is one of the four ``0003`` seeded (``0017`` made usdt-m Bybit's)."""
    ids = {
        name: uuid4() for name in ("strategy", "signal", "reservation", "attempt", "discrepancy")
    }
    statements = [
        "INSERT INTO exchange_credentials (exchange, label, wrapped_dek, dek_nonce, "
        "api_key_ciphertext, api_key_nonce, api_secret_ciphertext, api_secret_nonce, "
        "api_key_last4, trade_capable, trade_capability_source, withdraw_check) "
        "VALUES (:exchange, 'main', '\\x00', '\\x00', '\\x00', '\\x00', '\\x00', '\\x00', "
        "'abcd', true, 'UNRECORDED', 'UNRECORDED')",
        "INSERT INTO pool_balance_snapshots (exchange, venue, settlement_currency, "
        "available, total, observed_at) "
        "VALUES (:exchange, :venue, :settlement_currency, 100, 100, now())",
        "INSERT INTO strategies (id, name, exchange, venue, settlement_currency, fill_mode) "
        "VALUES (:strategy, 'owned', :exchange, :venue, :settlement_currency, 'PARTIAL')",
        "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
        "contracts, position_size, price, symbol, signal_type) "
        "VALUES (:signal, :strategy, 'k-1', '{}', 'buy', 1, 1, 1, 'SOLUSDT.P', 'x')",
        "INSERT INTO reservations (id, strategy_id, signal_id, exchange, venue, "
        "settlement_currency, amount, expires_at) "
        "VALUES (:reservation, :strategy, :signal, :exchange, :venue, :settlement_currency, "
        "10, now() + interval '1 hour')",
        "INSERT INTO execution_attempts (id, reservation_id, exchange, venue, "
        "settlement_currency, symbol, side, status, client_order_id, quantity) "
        "VALUES (:attempt, :reservation, :exchange, :venue, :settlement_currency, "
        "'SOLUSDT', 'BUY', 'FILLED', 'c-1', 0.5)",
        "INSERT INTO ledger_entries (strategy_id, allocation_id, execution_attempt_id, "
        "exchange, venue, settlement_currency, symbol, side, quantity, price, fee_currency, "
        "notional, exchange_order_id, exchange_fill_id, filled_at, usd_rate_at_fill) "
        "VALUES (:strategy, :reservation, :attempt, :exchange, :venue, :settlement_currency, "
        "'SOLUSDT', 'BUY', 0.5, 20, 'USDT', 10, 'o-1', 'f-1', now(), 1)",
        "INSERT INTO reconciliation_discrepancies (id, exchange, venue, settlement_currency, "
        "symbol, kind, venue_net_base, ledger_net_base, first_scan_id, last_scan_id) "
        "VALUES (:discrepancy, :exchange, :venue, :settlement_currency, 'SOLUSDT', "
        "'ATTRIBUTABLE_SINGLE_ALLOCATION', 0, 0.5, gen_random_uuid(), "
        "gen_random_uuid())",
        "INSERT INTO booking_proposals (discrepancy_id, exchange, venue, settlement_currency, "
        "symbol, kind, allocation_id, strategy_id, side, quantity, observed_venue_net_base, "
        "observed_ledger_net_base, observed_allocation_ids, fills, client_order_id, "
        "expires_at, prepared_by_job_id) "
        "VALUES (:discrepancy, :exchange, :venue, :settlement_currency, 'SOLUSDT', "
        "'ATTRIBUTABLE_SINGLE_ALLOCATION', :reservation, :strategy, 'SELL', 0.5, 0, 0.5, "
        "ARRAY[CAST(:reservation AS uuid)], '[{}]', 'c-2', now() + interval '1 hour', "
        "gen_random_uuid())",
    ]
    for statement in statements:
        _query(database_url, statement, {**ids, **_POOL})
    return ids


def _version(database_url: str) -> str:
    return str(_scalar(database_url, "SELECT version_num FROM alembic_version"))


@pytest.fixture
def at_0029() -> Iterator[Callable[[str], str]]:
    """A fresh database at ``0029`` per call, dropped at teardown."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_database(f"{_DB_PREFIX}_{suffix}", "0029")
        )


@pytest.fixture(scope="module")
def owned() -> Iterator[tuple[str, UUID, dict[str, UUID]]]:
    """Seeded at ``0029`` with one user, then upgraded: shared, read-mostly."""
    with migrated_database(f"{_DB_PREFIX}_owned", "0029") as url:
        owner = _add_user(url, "owner@example.com")
        ids = _seed_owned_rows(url)
        xmins = _query(url, "SELECT id, xmin::text FROM ledger_entries ORDER BY id")
        _alembic_ok(url, "upgrade", "0030")
        yield url, owner, {**ids, "ledger_xmins": xmins}  # type: ignore[dict-item]


@pytest.fixture
async def conn(owned: tuple[str, UUID, dict[str, UUID]]) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(owned[0], pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()


# --- the backfill -----------------------------------------------------------


def test_every_existing_row_becomes_the_owners(owned: tuple[str, UUID, dict[str, UUID]]) -> None:
    url, owner, _ = owned

    for table in _OWNED_TABLES:
        total, theirs = _query(
            url,
            f"SELECT count(*), count(*) FILTER (WHERE user_id = :owner) FROM {table}",
            {"owner": owner},
        )[0]
        assert total > 0, table
        assert theirs == total, table
    assert (
        _scalar(url, "SELECT bool_and(author_id = :owner) FROM strategies", {"owner": owner})
        is True
    )


def test_the_ledger_is_not_rewritten(owned: tuple[str, UUID, dict[str, UUID]]) -> None:
    url, _, ids = owned

    after = _query(url, "SELECT id, xmin::text FROM ledger_entries ORDER BY id")

    assert after == ids["ledger_xmins"]  # type: ignore[comparison-overlap]


def test_no_owner_column_keeps_a_default(owned: tuple[str, UUID, dict[str, UUID]]) -> None:
    url, _, _ = owned

    defaults = _query(
        url,
        "SELECT table_name FROM information_schema.columns "
        "WHERE column_name IN ('user_id', 'author_id') AND column_default IS NOT NULL",
    )

    assert defaults == []


def test_every_pool_reference_points_at_the_pool_of_its_market(
    owned: tuple[str, UUID, dict[str, UUID]],
) -> None:
    url, _, _ = owned

    for table in _POOL_REFERENCES:
        mismatched = _scalar(
            url,
            f"SELECT count(*) FROM {table} t JOIN capital_pools p ON p.id = t.pool_id "
            "WHERE (p.exchange, p.venue, p.settlement_currency, p.user_id) "
            "IS DISTINCT FROM (t.exchange, t.venue, t.settlement_currency, t.user_id)",
        )
        unset = _scalar(url, f"SELECT count(*) FROM {table} WHERE pool_id IS NULL")
        assert (mismatched, unset) == (0, 0), table


def test_a_pool_and_its_snapshot_are_keyed_by_the_pool_id(
    owned: tuple[str, UUID, dict[str, UUID]],
) -> None:
    url, _, _ = owned

    keys = dict(
        _query(
            url,
            "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE contype = 'p' AND conrelid::regclass::text "
            "IN ('capital_pools', 'pool_balance_snapshots')",
        )
    )

    assert keys == {
        "capital_pools": "PRIMARY KEY (id)",
        "pool_balance_snapshots": "PRIMARY KEY (pool_id)",
    }


# --- refusals ---------------------------------------------------------------


def test_refuses_to_guess_between_two_users(at_0029: Callable[[str], str]) -> None:
    url = at_0029("two_users")
    _add_user(url, "owner@example.com")
    _add_user(url, "other@example.com")
    _seed_owned_rows(url)

    result = _alembic(url, "upgrade", "0030")

    assert result.returncode != 0
    assert "exactly one user" in result.stderr
    assert "found 2" in result.stderr
    assert _version(url) == "0029"


def test_refuses_data_that_nobody_signed_in_to_own(at_0029: Callable[[str], str]) -> None:
    url = at_0029("no_user")
    _seed_owned_rows(url)

    result = _alembic(url, "upgrade", "0030")

    assert result.returncode != 0
    assert "found 0" in result.stderr
    assert _version(url) == "0029"


def test_a_database_nobody_signed_into_drops_its_seeded_pools(
    at_0029: Callable[[str], str],
) -> None:
    url = at_0029("fresh")
    assert _scalar(url, "SELECT count(*) FROM capital_pools") == 4

    _alembic_ok(url, "upgrade", "0030")

    assert _scalar(url, "SELECT count(*) FROM capital_pools") == 0


# --- what the constraints now allow and refuse ------------------------------


async def _insert_key(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(
        text(
            "INSERT INTO exchange_credentials (user_id, exchange, label, wrapped_dek, "
            "dek_nonce, api_key_ciphertext, api_key_nonce, api_secret_ciphertext, "
            "api_secret_nonce, api_key_last4, trade_capable, trade_capability_source, "
            "withdraw_check) VALUES (:user_id, 'bybit', 'main', '\\x00', '\\x00', '\\x00', "
            "'\\x00', '\\x00', '\\x00', 'wxyz', true, 'UNRECORDED', 'UNRECORDED')"
        ),
        {"user_id": user_id},
    )


async def _insert_pool(conn: AsyncConnection, user_id: UUID) -> int:
    inserted = await conn.execute(
        text(
            "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
            "min_order_size) VALUES (:user_id, :exchange, :venue, :settlement_currency, 5) "
            "RETURNING id"
        ),
        {"user_id": user_id, **_POOL},
    )
    return int(inserted.scalar_one())


async def _new_user(conn: AsyncConnection) -> UUID:
    user_id = uuid4()
    await conn.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email)"),
        {"id": user_id, "email": f"{user_id}@example.com"},
    )
    return user_id


async def test_another_user_holds_an_active_key_on_the_same_exchange(
    conn: AsyncConnection,
) -> None:
    other = await _new_user(conn)

    await _insert_key(conn, other)

    count = await conn.execute(
        text("SELECT count(*) FROM exchange_credentials WHERE exchange = 'bybit' AND is_active")
    )
    assert count.scalar_one() == 2


async def test_one_user_still_holds_one_active_key_per_exchange(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_key(conn, owned[1])

    assert _constraint_name(caught.value) == _ACTIVE_KEY


async def test_another_user_holds_a_pool_on_the_same_market(conn: AsyncConnection) -> None:
    other = await _new_user(conn)

    await _insert_pool(conn, other)

    count = await conn.execute(
        text("SELECT count(*) FROM capital_pools WHERE exchange = 'bybit' AND venue = 'usdt-m'")
    )
    assert count.scalar_one() == 2


async def test_one_user_holds_one_pool_per_market(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_pool(conn, owned[1])

    assert _constraint_name(caught.value) == _POOL_PER_USER


async def test_a_reservation_cannot_hold_money_in_another_users_pool(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    _, owner, ids = owned
    other = await _new_user(conn)
    owners_pool = (await conn.execute(text(_POOL_OF_USER), {"u": owner})).scalar_one()
    signal = uuid4()
    await conn.execute(
        text(
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) VALUES (:id, :strategy, "
            "'k-2', '{}', 'buy', 1, 1, 1, 'SOLUSDT.P', 'x')"
        ),
        {"id": signal, "strategy": ids["strategy"]},
    )

    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text(
                "INSERT INTO reservations (user_id, pool_id, strategy_id, signal_id, exchange, "
                "venue, settlement_currency, amount, expires_at) VALUES (:user_id, :pool_id, "
                ":strategy, :signal, :exchange, :venue, :settlement_currency, 10, "
                "now() + interval '1 hour')"
            ),
            {
                "user_id": other,
                "pool_id": owners_pool,
                "strategy": ids["strategy"],
                "signal": signal,
                **_POOL,
            },
        )

    assert _constraint_name(caught.value) == _RESERVATION_POOL


async def _insert_fill(conn: AsyncConnection, user_id: UUID, ids: dict[str, UUID]) -> None:
    await conn.execute(
        text(
            "INSERT INTO ledger_entries (user_id, strategy_id, allocation_id, "
            "execution_attempt_id, exchange, venue, settlement_currency, symbol, side, "
            "quantity, price, fee_currency, notional, exchange_order_id, exchange_fill_id, "
            "filled_at, usd_rate_at_fill) VALUES (:user_id, :strategy, :reservation, "
            ":attempt, :exchange, :venue, :settlement_currency, 'SOLUSDT', 'BUY', 0.5, 20, "
            "'USDT', 10, 'o-1', 'f-1', now(), 1)"
        ),
        {"user_id": user_id, **ids, **_POOL},
    )


async def test_the_same_venue_fill_id_may_belong_to_two_users(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    other = await _new_user(conn)

    await _insert_fill(conn, other, owned[2])


async def test_one_user_records_a_venue_fill_once(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_fill(conn, owned[1], owned[2])

    assert _constraint_name(caught.value) == _LEDGER_FILL


async def _insert_discrepancy(conn: AsyncConnection, user_id: UUID, pool_id: int) -> None:
    await conn.execute(
        text(
            "INSERT INTO reconciliation_discrepancies (user_id, pool_id, exchange, venue, "
            "settlement_currency, symbol, kind, venue_net_base, ledger_net_base, "
            "first_scan_id, last_scan_id) VALUES (:user_id, :pool_id, :exchange, :venue, "
            ":settlement_currency, 'SOLUSDT', 'ATTRIBUTABLE_SINGLE_ALLOCATION', 0, 0.5, "
            "gen_random_uuid(), gen_random_uuid())"
        ),
        {"user_id": user_id, "pool_id": pool_id, **_POOL},
    )


async def test_each_user_has_their_own_open_discrepancy_per_symbol(
    conn: AsyncConnection,
) -> None:
    other = await _new_user(conn)
    pool_id = await _insert_pool(conn, other)

    await _insert_discrepancy(conn, other, pool_id)


async def test_one_user_has_one_open_discrepancy_per_symbol(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    owner = owned[1]
    pool_id = (await conn.execute(text(_POOL_OF_USER), {"u": owner})).scalar_one()

    with pytest.raises(IntegrityError) as caught:
        await _insert_discrepancy(conn, owner, pool_id)

    assert _constraint_name(caught.value) == _OPEN_DISCREPANCY


async def _insert_strategy(
    conn: AsyncConnection, author: UUID, *, exchange: str, venue: str
) -> None:
    await conn.execute(
        text(
            "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
            "fill_mode) VALUES (:id, :author, :name, :exchange, :venue, 'USDT', 'PARTIAL')"
        ),
        {
            "id": uuid4(),
            "author": author,
            "name": f"s-{uuid4()}",
            "exchange": exchange,
            "venue": venue,
        },
    )


async def test_a_strategy_names_a_market_without_a_pool_row(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    """AD3: a strategy says where it trades; whose pool backs it is the
    subscriber's. No ``capital_pools`` row exists for binance here."""
    await _insert_strategy(conn, owned[1], exchange="binance", venue="usdt-m")


async def test_a_strategy_still_names_only_a_known_venue(
    conn: AsyncConnection, owned: tuple[str, UUID, dict[str, UUID]]
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await _insert_strategy(conn, owned[1], exchange="bybit", venue="margin")

    assert _constraint_name(caught.value) == _STRATEGY_VENUE


# --- downgrade --------------------------------------------------------------


def test_downgrade_restores_0029_and_upgrades_again(at_0029: Callable[[str], str]) -> None:
    url = at_0029("downgrade")
    _add_user(url, "owner@example.com")
    _seed_owned_rows(url)
    counts = [_scalar(url, f"SELECT count(*) FROM {table}") for table in _OWNED_TABLES]
    _alembic_ok(url, "upgrade", "0030")

    _alembic_ok(url, "downgrade", "0029")

    assert _version(url) == "0029"
    assert [_scalar(url, f"SELECT count(*) FROM {table}") for table in _OWNED_TABLES] == counts
    assert (
        _query(
            url,
            "SELECT table_name FROM information_schema.columns "
            "WHERE column_name IN ('user_id', 'author_id', 'pool_id') AND table_schema = 'public'",
        )
        == []
    )
    assert _scalar(
        url,
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'fk_strategies_capital_pool'",
    ) == (
        "FOREIGN KEY (exchange, venue, settlement_currency) "
        "REFERENCES capital_pools(exchange, venue, settlement_currency)"
    )

    _alembic_ok(url, "upgrade", "0030")
    assert _version(url) == "0030"


def test_downgrade_refuses_once_a_second_user_exists(at_0029: Callable[[str], str]) -> None:
    url = at_0029("downgrade_two_users")
    _add_user(url, "owner@example.com")
    _seed_owned_rows(url)
    _alembic_ok(url, "upgrade", "0030")
    _add_user(url, "other@example.com")

    result = _alembic(url, "downgrade", "0029")

    assert result.returncode != 0
    assert "found 2" in result.stderr
    assert _version(url) == "0030"

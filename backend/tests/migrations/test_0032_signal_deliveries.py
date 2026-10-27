"""Migration ``0032`` -- ``signal_deliveries`` (multi-user design AD5; tasks.md C.2).

A delivery is one signal reaching one subscription. The migration gives every
existing signal one delivery, for its strategy author's subscription (the one
0031 made), copying the signal's outcome columns, and points each reservation
and each attempt that has a reservation at that delivery.

``reservations.delivery_id`` stays NULLABLE and the unique on
``reservations.signal_id`` stays until C.6 (owner's choice, 2026-10-27).

Real PostgreSQL. Each migration scenario seeds a database at ``0031`` and
upgrades it; the constraint tests share one module-scoped database and roll back.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from tests.pg_head_schema import migrated_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_PREFIX = "strategy_manager_test_deliveries"

_PER_SUBSCRIPTION_UNIQUE = "ux_signal_deliveries_signal_subscription"
_RESERVATION_UNIQUE = "ux_reservations_delivery"
_DECIDED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


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


def _add_pool(database_url: str, user_id: UUID) -> int:
    return int(
        _scalar(
            database_url,
            "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
            "min_order_size) VALUES (:u, 'binance', 'usdt-m', 'USDT', 5) RETURNING id",
            {"u": user_id},
        )
    )


def _add_strategy(database_url: str, author: UUID, name: str) -> UUID:
    strategy_id = uuid4()
    _query(
        database_url,
        "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
        "fill_mode, allocation_percent) "
        "VALUES (:id, :author, :name, 'binance', 'usdt-m', 'USDT', 'PARTIAL', 30)",
        {"id": strategy_id, "author": author, "name": name},
    )
    return strategy_id


def _subscribe(database_url: str, user_id: UUID, strategy_id: UUID, pool_id: int) -> UUID:
    subscription_id = uuid4()
    _query(
        database_url,
        "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
        "VALUES (:id, :u, :s, :p, 20)",
        {"id": subscription_id, "u": user_id, "s": strategy_id, "p": pool_id},
    )
    return subscription_id


def _add_signal(
    database_url: str,
    strategy_id: UUID,
    *,
    status: str = "ACCEPTED",
    reason: str | None = None,
    detail: str | None = None,
    decided_at: datetime | None = None,
) -> UUID:
    signal_id = uuid4()
    _query(
        database_url,
        "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, status, action, "
        "contracts, position_size, price, symbol, signal_type, outcome_reason, "
        "outcome_detail, decided_at) "
        "VALUES (:id, :strategy, :key, '{}'::jsonb, :status, 'buy', 1, 1, 100, 'BTCUSDT', "
        "'ENTRY', :reason, :detail, :decided_at)",
        {
            "id": signal_id,
            "strategy": strategy_id,
            "key": str(uuid4()),
            "status": status,
            "reason": reason,
            "detail": detail,
            "decided_at": decided_at,
        },
    )
    return signal_id


def _add_reservation(
    database_url: str, user_id: UUID, pool_id: int, strategy_id: UUID, signal_id: UUID
) -> UUID:
    reservation_id = uuid4()
    _query(
        database_url,
        "INSERT INTO reservations (id, user_id, pool_id, strategy_id, signal_id, exchange, "
        "venue, settlement_currency, amount, expires_at) "
        "VALUES (:id, :u, :p, :s, :sig, 'binance', 'usdt-m', 'USDT', 10, now() + interval '1 day')",
        {"id": reservation_id, "u": user_id, "p": pool_id, "s": strategy_id, "sig": signal_id},
    )
    return reservation_id


def _add_attempt(
    database_url: str,
    user_id: UUID,
    *,
    reservation_id: UUID | None = None,
    closes_allocation_id: UUID | None = None,
    signal_id: UUID | None = None,
) -> UUID:
    attempt_id = uuid4()
    _query(
        database_url,
        "INSERT INTO execution_attempts (id, user_id, reservation_id, closes_allocation_id, "
        "signal_id, exchange, venue, settlement_currency, symbol, side, quantity, status, "
        "client_order_id) VALUES (:id, :u, :r, :c, :sig, 'binance', 'usdt-m', 'USDT', "
        "'BTCUSDT', 'BUY', 1, 'FILLED', :coid)",
        {
            "id": attempt_id,
            "u": user_id,
            "r": reservation_id,
            "c": closes_allocation_id,
            "sig": signal_id,
            "coid": str(uuid4()),
        },
    )
    return attempt_id


@pytest.fixture
def at_0031() -> Iterator[Callable[[str], str]]:
    """A fresh database at ``0031`` per call, dropped at teardown."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_database(f"{_DB_PREFIX}_{suffix}", "0031")
        )


class Seeded:
    """Two users; the owner authors two strategies and the other user also
    subscribes to the first, so the author's subscription must be picked."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.owner = _add_user(url, "owner@example.com")
        self.other = _add_user(url, "other@example.com")
        self.owner_pool = _add_pool(url, self.owner)
        self.other_pool = _add_pool(url, self.other)
        self.alpha = _add_strategy(url, self.owner, "alpha")
        self.beta = _add_strategy(url, self.owner, "beta")
        self.owner_alpha_sub = _subscribe(url, self.owner, self.alpha, self.owner_pool)
        self.owner_beta_sub = _subscribe(url, self.owner, self.beta, self.owner_pool)
        self.other_alpha_sub = _subscribe(url, self.other, self.alpha, self.other_pool)
        self.accepted = _add_signal(url, self.alpha)
        self.processed = _add_signal(
            url, self.alpha, status="PROCESSED", detail="opened", decided_at=_DECIDED_AT
        )
        self.rejected = _add_signal(
            url,
            self.beta,
            status="REJECTED",
            reason="NO_CAPITAL",
            detail="nothing left",
            decided_at=_DECIDED_AT,
        )
        self.accepted_reservation = _add_reservation(
            url, self.owner, self.owner_pool, self.alpha, self.accepted
        )
        self.processed_reservation = _add_reservation(
            url, self.owner, self.owner_pool, self.alpha, self.processed
        )
        # An opening attempt written before 0025: no signal_id of its own.
        self.opening_without_signal = _add_attempt(
            url, self.owner, reservation_id=self.accepted_reservation
        )
        self.opening_with_signal = _add_attempt(
            url,
            self.owner,
            reservation_id=self.processed_reservation,
            signal_id=self.processed,
        )
        # A closing attempt has no reservation of its own. From 0025 on it
        # carries the closing signal; one written before 0025 carries only
        # the reservation it closes.
        self.closed = _add_signal(
            url, self.alpha, status="PROCESSED", detail="closed", decided_at=_DECIDED_AT
        )
        self.closing = _add_attempt(
            url,
            self.owner,
            closes_allocation_id=self.processed_reservation,
            signal_id=self.closed,
        )
        self.closing_without_signal = _add_attempt(
            url, self.owner, closes_allocation_id=self.processed_reservation
        )


@pytest.fixture(scope="module")
def seeded() -> Iterator[Seeded]:
    """Seeded at ``0031``, then upgraded: shared, read-mostly."""
    with migrated_database(f"{_DB_PREFIX}_seeded", "0031") as url:
        data = Seeded(url)
        _alembic_ok(url, "upgrade", "0032")
        yield data


@pytest.fixture
async def conn(seeded: Seeded) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(seeded.url, pool_pre_ping=True)
    async with engine.connect() as connection:
        yield connection
        await connection.rollback()
    await engine.dispose()


# --- the backfill -----------------------------------------------------------


def test_every_signal_has_exactly_one_delivery_for_its_authors_subscription(
    seeded: Seeded,
) -> None:
    rows = _query(
        seeded.url,
        "SELECT signal_id, subscription_id, user_id FROM signal_deliveries ORDER BY signal_id",
    )

    expected = sorted(
        [
            (seeded.accepted, seeded.owner_alpha_sub, seeded.owner),
            (seeded.processed, seeded.owner_alpha_sub, seeded.owner),
            (seeded.closed, seeded.owner_alpha_sub, seeded.owner),
            (seeded.rejected, seeded.owner_beta_sub, seeded.owner),
        ]
    )
    assert rows == expected


def test_the_deliverys_outcome_columns_equal_its_signals(seeded: Seeded) -> None:
    rows = _query(
        seeded.url,
        "SELECT d.status, d.outcome_reason, d.outcome_detail, d.decided_at, d.created_at "
        "FROM signal_deliveries d JOIN signals s ON s.id = d.signal_id "
        "ORDER BY s.received_at, s.id",
    )
    signals = _query(
        seeded.url,
        "SELECT s.status, s.outcome_reason, s.outcome_detail, s.decided_at, s.received_at "
        "FROM signals s ORDER BY s.received_at, s.id",
    )

    rejected = [row[:4] for row in rows if row[0] == "REJECTED"]
    assert len(rows) == 4
    assert rows == signals
    assert rejected == [("REJECTED", "NO_CAPITAL", "nothing left", _DECIDED_AT)]


def test_the_signals_keep_their_outcome_columns(seeded: Seeded) -> None:
    row = _query(
        seeded.url,
        "SELECT status, outcome_reason, outcome_detail, decided_at FROM signals WHERE id = :s",
        {"s": seeded.rejected},
    )[0]

    assert row == ("REJECTED", "NO_CAPITAL", "nothing left", _DECIDED_AT)


def test_every_reservation_points_at_its_signals_delivery(seeded: Seeded) -> None:
    rows = _query(
        seeded.url,
        "SELECT r.id, d.signal_id = r.signal_id FROM reservations r "
        "JOIN signal_deliveries d ON d.id = r.delivery_id",
    )
    unfilled = _scalar(seeded.url, "SELECT count(*) FROM reservations WHERE delivery_id IS NULL")

    assert sorted(row[0] for row in rows) == sorted(
        [seeded.accepted_reservation, seeded.processed_reservation]
    )
    assert all(row[1] for row in rows)
    assert unfilled == 0


def test_an_attempt_without_a_signal_id_gets_its_delivery_through_its_reservation(
    seeded: Seeded,
) -> None:
    rows = dict(
        _query(
            seeded.url,
            "SELECT a.id, d.signal_id FROM execution_attempts a "
            "JOIN signal_deliveries d ON d.id = a.delivery_id",
        )
    )

    opening = {a: rows.get(a) for a in (seeded.opening_without_signal, seeded.opening_with_signal)}
    assert opening == {
        seeded.opening_without_signal: seeded.accepted,
        seeded.opening_with_signal: seeded.processed,
    }


def test_a_closing_attempt_gets_its_closing_signals_delivery(seeded: Seeded) -> None:
    signal = _scalar(
        seeded.url,
        "SELECT d.signal_id FROM execution_attempts a "
        "LEFT JOIN signal_deliveries d ON d.id = a.delivery_id WHERE a.id = :a",
        {"a": seeded.closing},
    )

    assert signal == seeded.closed


def test_a_closing_attempt_from_before_0025_gets_the_closed_reservations_delivery(
    seeded: Seeded,
) -> None:
    """Its closing signal was never recorded. The reservation it closes names
    the same subscription, which is what a delivery is read for."""
    signal = _scalar(
        seeded.url,
        "SELECT d.signal_id FROM execution_attempts a "
        "LEFT JOIN signal_deliveries d ON d.id = a.delivery_id WHERE a.id = :a",
        {"a": seeded.closing_without_signal},
    )

    assert signal == seeded.processed


def test_every_attempt_gets_a_delivery(seeded: Seeded) -> None:
    unfilled = _scalar(
        seeded.url, "SELECT count(*) FROM execution_attempts WHERE delivery_id IS NULL"
    )

    assert unfilled == 0


def test_an_empty_database_migrates(at_0031: Callable[[str], str]) -> None:
    url = at_0031("empty")

    _alembic_ok(url, "upgrade", "0032")

    version = _version(url)
    deliveries = _scalar(url, "SELECT count(*) FROM signal_deliveries")
    assert version == "0032"
    assert deliveries == 0


def test_refuses_a_signal_whose_strategy_has_no_author_subscription(
    at_0031: Callable[[str], str],
) -> None:
    url = at_0031("no_subscription")
    owner = _add_user(url, "owner@example.com")
    pool = _add_pool(url, owner)
    covered = _add_strategy(url, owner, "covered")
    bare = _add_strategy(url, owner, "bare")
    _subscribe(url, owner, covered, pool)
    _add_signal(url, covered)
    orphan = _add_signal(url, bare)

    result = _alembic(url, "upgrade", "0032")

    assert result.returncode != 0
    assert str(orphan) in result.stderr
    version = _version(url)
    assert version == "0031"
    tables = _scalar(
        url,
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'signal_deliveries'",
    )
    columns = _scalar(
        url,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'reservations' AND column_name = 'delivery_id'",
    )
    assert tables == 0
    assert columns == 0


# --- the constraints --------------------------------------------------------


async def test_a_second_delivery_of_one_signal_to_one_subscription_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text(
                "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
                "VALUES (:id, :sig, :sub, :u)"
            ),
            {
                "id": uuid4(),
                "sig": seeded.accepted,
                "sub": seeded.owner_alpha_sub,
                "u": seeded.owner,
            },
        )

    assert _constraint_name(caught.value) == _PER_SUBSCRIPTION_UNIQUE


async def test_another_subscription_may_receive_the_same_signal(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    await conn.execute(
        text(
            "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
            "VALUES (:id, :sig, :sub, :u)"
        ),
        {
            "id": uuid4(),
            "sig": seeded.accepted,
            "sub": seeded.other_alpha_sub,
            "u": seeded.other,
        },
    )

    count = await conn.execute(
        text("SELECT count(*) FROM signal_deliveries WHERE signal_id = :s"),
        {"s": seeded.accepted},
    )
    assert count.scalar_one() == 2


async def test_a_new_delivery_starts_accepted(conn: AsyncConnection, seeded: Seeded) -> None:
    delivery = uuid4()
    await conn.execute(
        text(
            "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
            "VALUES (:id, :sig, :sub, :u)"
        ),
        {"id": delivery, "sig": seeded.accepted, "sub": seeded.other_alpha_sub, "u": seeded.other},
    )

    status = await conn.execute(
        text("SELECT status FROM signal_deliveries WHERE id = :id"), {"id": delivery}
    )
    assert status.scalar_one() == "ACCEPTED"


async def test_an_unknown_delivery_status_is_refused(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text(
                "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id, status) "
                "VALUES (:id, :sig, :sub, :u, 'PAUSED')"
            ),
            {
                "id": uuid4(),
                "sig": seeded.accepted,
                "sub": seeded.other_alpha_sub,
                "u": seeded.other,
            },
        )

    assert _constraint_name(caught.value) == "ck_signal_deliveries_status"


async def test_two_reservations_cannot_share_one_delivery(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    delivery = (
        await conn.execute(
            text("SELECT delivery_id FROM reservations WHERE id = :r"),
            {"r": seeded.accepted_reservation},
        )
    ).scalar_one()

    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text("UPDATE reservations SET delivery_id = :d WHERE id = :r"),
            {"d": delivery, "r": seeded.processed_reservation},
        )

    assert _constraint_name(caught.value) == _RESERVATION_UNIQUE


async def test_a_reservation_without_a_delivery_is_still_accepted(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    signal = uuid4()
    await conn.execute(
        text(
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) "
            "VALUES (:id, :s, :k, '{}'::jsonb, 'buy', 1, 1, 100, 'BTCUSDT', 'ENTRY')"
        ),
        {"id": signal, "s": seeded.beta, "k": str(uuid4())},
    )

    await conn.execute(
        text(
            "INSERT INTO reservations (id, user_id, pool_id, strategy_id, signal_id, exchange, "
            "venue, settlement_currency, amount, expires_at) "
            "VALUES (:id, :u, :p, :s, :sig, 'binance', 'usdt-m', 'USDT', 10, "
            "now() + interval '1 day')"
        ),
        {
            "id": uuid4(),
            "u": seeded.owner,
            "p": seeded.owner_pool,
            "s": seeded.beta,
            "sig": signal,
        },
    )

    nullable = await conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'reservations' AND column_name = 'delivery_id'"
        )
    )
    assert nullable.scalar_one() == "YES"


async def test_the_unique_on_reservations_signal_id_stays(
    conn: AsyncConnection, seeded: Seeded
) -> None:
    with pytest.raises(IntegrityError) as caught:
        await conn.execute(
            text(
                "INSERT INTO reservations (id, user_id, pool_id, strategy_id, signal_id, "
                "exchange, venue, settlement_currency, amount, expires_at) "
                "VALUES (:id, :u, :p, :s, :sig, 'binance', 'usdt-m', 'USDT', 10, "
                "now() + interval '1 day')"
            ),
            {
                "id": uuid4(),
                "u": seeded.owner,
                "p": seeded.owner_pool,
                "s": seeded.alpha,
                "sig": seeded.accepted,
            },
        )

    assert _constraint_name(caught.value) == "reservations_signal_id_key"


async def test_deliveries_are_indexed_by_user(conn: AsyncConnection) -> None:
    result = await conn.execute(
        text(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'signal_deliveries' "
            "AND indexname = 'ix_signal_deliveries_user_id'"
        )
    )

    assert result.scalar_one() == 1


# --- downgrade --------------------------------------------------------------


def test_downgrade_drops_the_deliveries_and_upgrades_again(
    at_0031: Callable[[str], str],
) -> None:
    url = at_0031("downgrade")
    data = Seeded(url)
    # The downgrade needs exactly one user: drop the other one and what it owns.
    _query(url, "DELETE FROM subscriptions WHERE user_id = :u", {"u": data.other})
    _query(url, "DELETE FROM capital_pools WHERE user_id = :u", {"u": data.other})
    _query(url, "DELETE FROM users WHERE id = :u", {"u": data.other})
    _alembic_ok(url, "upgrade", "0032")

    _alembic_ok(url, "downgrade", "0031")

    version = _version(url)
    assert version == "0031"
    leftovers = _scalar(
        url,
        "SELECT count(*) FROM information_schema.columns WHERE column_name = 'delivery_id' "
        "AND table_name IN ('reservations', 'execution_attempts')",
    )
    tables = _scalar(
        url,
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'signal_deliveries'",
    )
    signals_outcome = _scalar(
        url, "SELECT outcome_reason FROM signals WHERE id = :s", {"s": data.rejected}
    )
    assert leftovers == 0
    assert tables == 0
    assert signals_outcome == "NO_CAPITAL"

    _alembic_ok(url, "upgrade", "0032")
    version = _version(url)
    deliveries = _scalar(url, "SELECT count(*) FROM signal_deliveries")
    unfilled = _scalar(url, "SELECT count(*) FROM reservations WHERE delivery_id IS NULL")
    assert version == "0032"
    assert deliveries == 4
    assert unfilled == 0


def test_downgrade_refuses_with_more_than_one_user(
    at_0031: Callable[[str], str],
) -> None:
    url = at_0031("downgrade_two_users")
    Seeded(url)
    _alembic_ok(url, "upgrade", "0032")

    result = _alembic(url, "downgrade", "0031")

    assert result.returncode != 0
    assert "found 2" in result.stderr
    version = _version(url)
    assert version == "0032"


def test_an_empty_database_downgrades(at_0031: Callable[[str], str]) -> None:
    """No user means no delivery to fold back, and the whole chain must still
    downgrade on an empty database (``test_0029_users``)."""
    url = at_0031("downgrade_no_users")
    _alembic_ok(url, "upgrade", "0032")

    result = _alembic(url, "downgrade", "0031")

    refused = result.returncode != 0
    version = _version(url)
    assert not refused
    assert version == "0031"

"""Migration ``0035`` -- the mode of a user and of a reservation (multi-user design
AD7; tasks.md E.1).

* ``users.mode`` is ``NOT NULL`` and defaults to ``SIMULATION`` (decision 6). Existing
  users get ``LIVE`` when ``DRY_RUN`` is false at migration time, so production keeps
  trading exactly as before the deploy.
* ``reservations.mode`` is ``NOT NULL`` with no default: a writer that forgets it fails
  loudly. Its backfill reads what each reservation left behind: any real fill or
  order is ``LIVE``, a fake one and no real one is ``SIMULATION``, and no evidence at
  all takes the mode the users get.
* It refuses, writing nothing, when an open allocation holds real and fake fills.

Real PostgreSQL. Each scenario seeds its own database at ``0034``, since the backfill
is what is being tested. The subprocess gets ``DRY_RUN`` explicitly, so no test
depends on the developer's ``.env``.
"""

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.pg_head_schema import migrated_database

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_DB_PREFIX = "strategy_manager_test_mode"

_LIVE = "LIVE"
_SIMULATION = "SIMULATION"
_USER_CHECK = "ck_users_mode"
_RESERVATION_CHECK = "ck_reservations_mode"


def _alembic(
    database_url: str, *args: str, dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    """Runs alembic in a subprocess so its own ``asyncio.run`` never collides
    with a running loop."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_BACKEND_DIR),
        env={
            **os.environ,
            "DATABASE_URL": database_url,
            "DRY_RUN": "true" if dry_run else "false",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_ok(database_url: str, *args: str, dry_run: bool = False) -> None:
    result = _alembic(database_url, *args, dry_run=dry_run)
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


def _column_exists(database_url: str, table: str, column: str) -> bool:
    return bool(
        _query(
            database_url,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c",
            {"t": table, "c": column},
        )
    )


def _user_mode(database_url: str, user_id: UUID) -> str:
    return str(_scalar(database_url, "SELECT mode FROM users WHERE id = :id", {"id": user_id}))


def _reservation_mode(database_url: str, reservation_id: UUID) -> str:
    return str(
        _scalar(
            database_url, "SELECT mode FROM reservations WHERE id = :id", {"id": reservation_id}
        )
    )


class World:
    """One user with a pool, a strategy and a subscription at ``0034``."""

    def __init__(self, url: str, email: str = "owner@example.com") -> None:
        self.url = url
        self.user = uuid4()
        _query(url, "INSERT INTO users (id, email) VALUES (:id, :e)", {"id": self.user, "e": email})
        self.pool = int(
            _scalar(
                url,
                "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
                "min_order_size) VALUES (:u, 'binance', 'usdt-m', 'USDT', 5) RETURNING id",
                {"u": self.user},
            )
        )
        self.strategy = uuid4()
        _query(
            url,
            "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
            "fill_mode, webhook_secret_hash, webhook_secret_last4) VALUES (:id, :u, :n, "
            "'binance', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash', 'fxtr')",
            {"id": self.strategy, "u": self.user, "n": f"strategy-{email}"},
        )
        self.subscription = uuid4()
        _query(
            url,
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
            "VALUES (:id, :u, :s, :p, 20)",
            {"id": self.subscription, "u": self.user, "s": self.strategy, "p": self.pool},
        )

    def reservation(self, *, status: str = "FILLED") -> UUID:
        signal = uuid4()
        _query(
            self.url,
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) VALUES (:id, :s, :k, "
            "'{}'::jsonb, 'buy', 1, 1, 2, 'BTCUSDT.P', 'ENTRY')",
            {"id": signal, "s": self.strategy, "k": str(uuid4())},
        )
        delivery = uuid4()
        _query(
            self.url,
            "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
            "VALUES (:id, :sig, :sub, :u)",
            {"id": delivery, "sig": signal, "sub": self.subscription, "u": self.user},
        )
        reservation = uuid4()
        terminal = status != "PENDING" and status != "SUBMITTED"
        _query(
            self.url,
            "INSERT INTO reservations (id, user_id, pool_id, strategy_id, signal_id, delivery_id, "
            "exchange, venue, settlement_currency, amount, status, expires_at, terminal_at, "
            "release_reason) VALUES (:id, :u, :p, :s, :sig, :d, 'binance', 'usdt-m', 'USDT', 10, "
            ":status, now() + interval '1 day', :terminal, :reason)",
            {
                "id": reservation,
                "u": self.user,
                "p": self.pool,
                "s": self.strategy,
                "sig": signal,
                "d": delivery,
                "status": status,
                "terminal": datetime(2026, 10, 1, tzinfo=UTC) if terminal else None,
                "reason": "EXCHANGE_ERROR" if status == "RELEASED" else None,
            },
        )
        return reservation

    def attempt(
        self,
        reservation: UUID,
        *,
        order_id: str | None,
        status: str = "FILLED",
        closing: bool = False,
    ) -> UUID:
        attempt = uuid4()
        _query(
            self.url,
            "INSERT INTO execution_attempts (id, user_id, reservation_id, closes_allocation_id, "
            "exchange, venue, settlement_currency, symbol, side, quantity, status, "
            "client_order_id, exchange_order_id) VALUES (:id, :u, :r, :c, 'binance', 'usdt-m', "
            "'USDT', 'BTCUSDT', :side, 1, :status, :coid, :order)",
            {
                "id": attempt,
                "u": self.user,
                "r": None if closing else reservation,
                "c": reservation if closing else None,
                "side": "SELL" if closing else "BUY",
                "status": status,
                "coid": str(uuid4()),
                "order": order_id,
            },
        )
        return attempt

    def fill(self, reservation: UUID, attempt: UUID, fill_id: str, *, side: str = "BUY") -> None:
        _query(
            self.url,
            "INSERT INTO ledger_entries (id, user_id, strategy_id, allocation_id, "
            "execution_attempt_id, exchange, venue, settlement_currency, symbol, side, quantity, "
            "price, fee, fee_currency, notional, exchange_order_id, exchange_fill_id, filled_at, "
            "usd_rate_at_fill) VALUES (:id, :u, :s, :alloc, :att, 'binance', 'usdt-m', 'USDT', "
            "'BTCUSDT', :side, 1, 2, 0, 'USDT', 2, 'order', :fill, now(), 1)",
            {
                "id": uuid4(),
                "u": self.user,
                "s": self.strategy,
                "alloc": reservation,
                "att": attempt,
                "side": side,
                "fill": fill_id,
            },
        )


@pytest.fixture
def at_0034() -> Iterator[Callable[[str], str]]:
    """A fresh database at ``0034`` per call, dropped at teardown."""
    with ExitStack() as stack:
        yield lambda suffix: stack.enter_context(
            migrated_database(f"{_DB_PREFIX}_{suffix}", "0034")
        )


# --- the users --------------------------------------------------------------


@pytest.mark.parametrize(("dry_run", "expected"), [(False, _LIVE), (True, _SIMULATION)])
def test_an_existing_user_keeps_trading_as_the_brake_said_at_migration(
    at_0034: Callable[[str], str], dry_run: bool, expected: str
) -> None:
    url = at_0034(f"user_{dry_run}".lower())
    world = World(url)

    _alembic_ok(url, "upgrade", "0035", dry_run=dry_run)

    assert _user_mode(url, world.user) == expected


def test_a_new_user_starts_in_simulation(at_0034: Callable[[str], str]) -> None:
    url = at_0034("new_user")
    _alembic_ok(url, "upgrade", "0035")

    world = World(url)

    assert _user_mode(url, world.user) == _SIMULATION


def test_a_user_mode_outside_the_two_is_refused(at_0034: Callable[[str], str]) -> None:
    url = at_0034("user_check")
    world = World(url)
    _alembic_ok(url, "upgrade", "0035")

    with pytest.raises(IntegrityError) as caught:
        _query(url, "UPDATE users SET mode = 'PAPER' WHERE id = :id", {"id": world.user})

    assert _constraint_name(caught.value) == _USER_CHECK


# --- the reservations' backfill ---------------------------------------------


def test_a_reservation_with_a_fake_fill_is_simulation(at_0034: Callable[[str], str]) -> None:
    url = at_0034("fake_fill")
    world = World(url)
    reservation = world.reservation()
    attempt = world.attempt(reservation, order_id="fake-order-1")
    world.fill(reservation, attempt, "fake-fill-1")

    _alembic_ok(url, "upgrade", "0035")

    assert _reservation_mode(url, reservation) == _SIMULATION


def test_a_reservation_with_a_real_fill_is_live_even_with_the_brake_on(
    at_0034: Callable[[str], str],
) -> None:
    url = at_0034("real_fill")
    world = World(url)
    reservation = world.reservation()
    attempt = world.attempt(reservation, order_id="123456")
    world.fill(reservation, attempt, "98765")

    _alembic_ok(url, "upgrade", "0035", dry_run=True)

    assert _reservation_mode(url, reservation) == _LIVE


def test_an_order_with_no_fill_yet_says_the_mode(at_0034: Callable[[str], str]) -> None:
    url = at_0034("orders")
    world = World(url)
    fake = world.reservation(status="SUBMITTED")
    world.attempt(fake, order_id="fake-order-2", status="SUBMITTED")
    real = world.reservation(status="SUBMITTED")
    world.attempt(real, order_id="123457", status="SUBMITTED")

    _alembic_ok(url, "upgrade", "0035", dry_run=True)

    assert _reservation_mode(url, fake) == _SIMULATION
    assert _reservation_mode(url, real) == _LIVE


@pytest.mark.parametrize(("dry_run", "expected"), [(False, _LIVE), (True, _SIMULATION)])
def test_no_evidence_takes_the_mode_the_users_get(
    at_0034: Callable[[str], str], dry_run: bool, expected: str
) -> None:
    url = at_0034(f"no_evidence_{dry_run}".lower())
    world = World(url)
    pending = world.reservation(status="PENDING")
    released = world.reservation(status="RELEASED")
    never_placed = world.reservation(status="SUBMITTED")
    world.attempt(never_placed, order_id=None, status="SUBMITTED")

    _alembic_ok(url, "upgrade", "0035", dry_run=dry_run)

    assert _reservation_mode(url, pending) == expected
    assert _reservation_mode(url, released) == expected
    assert _reservation_mode(url, never_placed) == expected


def test_a_closed_allocation_with_both_kinds_of_fill_is_live(
    at_0034: Callable[[str], str],
) -> None:
    """Real money moved, so it can never read as a rehearsal."""
    url = at_0034("closed_mixed")
    world = World(url)
    reservation = world.reservation()
    opening = world.attempt(reservation, order_id="fake-order-3")
    world.fill(reservation, opening, "fake-fill-3")
    closing = world.attempt(reservation, order_id="123458", closing=True)
    world.fill(reservation, closing, "98766", side="SELL")

    _alembic_ok(url, "upgrade", "0035")

    assert _reservation_mode(url, reservation) == _LIVE


def test_a_closing_order_is_evidence_too(at_0034: Callable[[str], str]) -> None:
    url = at_0034("closing_order")
    world = World(url)
    reservation = world.reservation(status="RELEASED")
    world.attempt(reservation, order_id="fake-order-4", status="SUBMITTED", closing=True)

    _alembic_ok(url, "upgrade", "0035")

    assert _reservation_mode(url, reservation) == _SIMULATION


# --- the refusal ------------------------------------------------------------


def test_refuses_an_open_allocation_with_both_kinds_of_fill(
    at_0034: Callable[[str], str],
) -> None:
    """No one mode can say how it closes, and a wrong guess sends a close to the wrong
    venue."""
    url = at_0034("open_mixed")
    world = World(url)
    reservation = world.reservation()
    attempt = world.attempt(reservation, order_id="123459")
    world.fill(reservation, attempt, "98767")
    world.fill(reservation, attempt, "fake-fill-4")

    result = _alembic(url, "upgrade", "0035")

    assert result.returncode != 0
    assert str(reservation) in result.stderr
    assert _version(url) == "0034"
    assert not _column_exists(url, "users", "mode")
    assert not _column_exists(url, "reservations", "mode")


# --- the constraints --------------------------------------------------------


def test_a_reservation_without_a_mode_is_refused(at_0034: Callable[[str], str]) -> None:
    url = at_0034("no_default")
    world = World(url)
    _alembic_ok(url, "upgrade", "0035")

    with pytest.raises(IntegrityError):
        world.reservation(status="PENDING")


def test_a_reservation_mode_outside_the_two_is_refused(at_0034: Callable[[str], str]) -> None:
    url = at_0034("reservation_check")
    world = World(url)
    reservation = world.reservation(status="PENDING")
    _alembic_ok(url, "upgrade", "0035")

    with pytest.raises(IntegrityError) as caught:
        _query(
            url, "UPDATE reservations SET mode = 'PAPER' WHERE id = :id", {"id": reservation}
        )

    assert _constraint_name(caught.value) == _RESERVATION_CHECK


# --- downgrade --------------------------------------------------------------


def test_downgrade_drops_both_columns_and_the_upgrade_runs_again(
    at_0034: Callable[[str], str],
) -> None:
    url = at_0034("downgrade")
    world = World(url)
    reservation = world.reservation()
    attempt = world.attempt(reservation, order_id="fake-order-5")
    world.fill(reservation, attempt, "fake-fill-5")
    _alembic_ok(url, "upgrade", "0035")

    _alembic_ok(url, "downgrade", "0034")

    assert _version(url) == "0034"
    assert not _column_exists(url, "users", "mode")
    assert not _column_exists(url, "reservations", "mode")

    _alembic_ok(url, "upgrade", "0035")
    assert _user_mode(url, world.user) == _LIVE
    assert _reservation_mode(url, reservation) == _SIMULATION


def test_downgrade_refuses_with_more_than_one_user(at_0034: Callable[[str], str]) -> None:
    url = at_0034("downgrade_users")
    world = World(url)
    World(url, "second@example.com")
    _alembic_ok(url, "upgrade", "0035")

    result = _alembic(url, "downgrade", "0034")

    assert result.returncode != 0
    assert _version(url) == "0035"
    assert _user_mode(url, world.user) == _LIVE

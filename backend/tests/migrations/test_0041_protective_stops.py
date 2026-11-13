"""Migration ``0041`` -- the protective stop of each opening (subscriber-safety SS.5).

* ``protective_stops`` holds one row per opening attempt: who, which allocation, the
  level the stop was placed at, the price it rests at, the id the venue gave it and where
  it stands (``PENDING``, ``RESTING``, ``FAILED``, ``GONE``, ``VOID``, ``SIMULATED``).
* One row per attempt (a UNIQUE on the attempt), the status and the level are checked by
  name, and a row cannot name an attempt, an allocation or a user that does not exist.
* The downgrade drops the table and leaves every other table as it was.

Real PostgreSQL, one database per scenario, seeded at ``0040``.
"""

from collections.abc import Iterator
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from tests.migrations.test_0038_strategy_sharing import (
    _alembic,
    _has_table,
    _query,
)
from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_DB_NAME = "strategy_manager_test_protective_stops"
_TABLE = "protective_stops"
_STATUS_CHECK = "ck_protective_stops_status"
_SIDE_CHECK = "ck_protective_stops_position_side"
_LEVEL_CHECK = "ck_protective_stops_stop_loss_pct_range"
_TRIGGER_CHECK = "ck_protective_stops_trigger_price_positive"
_ATTEMPT_UNIQUE = "uq_protective_stops_attempt"
_ATTEMPT_FK = "fk_protective_stops_attempt"
_ALLOCATION_FK = "fk_protective_stops_allocation"
_USER_FK = "fk_protective_stops_user"
_INDEXES = {"ix_protective_stops_allocation_id", "ix_protective_stops_user_id"}
_STATUSES = ["PENDING", "RESTING", "FAILED", "GONE", "VOID", "SIMULATED"]


@pytest.fixture
def at_0040() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0040") as url:
        yield url


class World:
    """One user with a pool, a strategy, a subscription, and openings written at ``0040``."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.user = uuid4()
        _query(
            url,
            "INSERT INTO users (id, email) VALUES (:id, 'owner@example.com')",
            {"id": self.user},
        )
        pool = _query(
            url,
            "INSERT INTO capital_pools (user_id, exchange, venue, settlement_currency, "
            "min_order_size) VALUES (:u, 'bybit', 'usdt-m', 'USDT', 5) RETURNING id",
            {"u": self.user},
        )[0][0]
        self.strategy = uuid4()
        _query(
            url,
            "INSERT INTO strategies (id, author_id, name, exchange, venue, settlement_currency, "
            "fill_mode, webhook_secret_hash, webhook_secret_last4) VALUES (:id, :u, 'first', "
            "'bybit', 'usdt-m', 'USDT', 'PARTIAL', 'fixture-hash', 'fxtr')",
            {"id": self.strategy, "u": self.user},
        )
        self.subscription = uuid4()
        _query(
            url,
            "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
            "VALUES (:id, :u, :s, :p, 20)",
            {"id": self.subscription, "u": self.user, "s": self.strategy, "p": pool},
        )
        self.pool = pool

    def opening(self) -> tuple[UUID, UUID]:
        """A reservation and the opening attempt that spent it: ``(allocation, attempt)``."""
        signal = uuid4()
        _query(
            self.url,
            "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
            "contracts, position_size, price, symbol, signal_type) VALUES (:id, :s, :k, "
            "'{}'::jsonb, 'buy', 1, 1, 2, 'DOGEUSDT.P', 'ENTRY')",
            {"id": signal, "s": self.strategy, "k": str(uuid4())},
        )
        delivery = uuid4()
        _query(
            self.url,
            "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
            "VALUES (:id, :sig, :sub, :u)",
            {"id": delivery, "sig": signal, "sub": self.subscription, "u": self.user},
        )
        allocation = uuid4()
        _query(
            self.url,
            "INSERT INTO reservations (id, user_id, pool_id, strategy_id, signal_id, "
            "delivery_id, exchange, venue, settlement_currency, amount, status, expires_at, "
            "mode) VALUES (:id, :u, :p, :s, :sig, :d, 'bybit', 'usdt-m', 'USDT', 10, "
            "'FILLED', now() + interval '1 day', 'LIVE')",
            {
                "id": allocation,
                "u": self.user,
                "p": self.pool,
                "s": self.strategy,
                "sig": signal,
                "d": delivery,
            },
        )
        attempt = uuid4()
        _query(
            self.url,
            "INSERT INTO execution_attempts (id, user_id, reservation_id, exchange, venue, "
            "settlement_currency, symbol, side, quantity, status, client_order_id) VALUES "
            "(:id, :u, :r, 'bybit', 'usdt-m', 'USDT', 'DOGEUSDT.P', 'BUY', 76, 'SUBMITTED', :c)",
            {"id": attempt, "u": self.user, "r": allocation, "c": str(uuid4())},
        )
        return allocation, attempt

    def stop(
        self,
        allocation: UUID,
        attempt: UUID,
        *,
        status: str = "PENDING",
        side: str = "LONG",
        level: str = "10",
        trigger: str | None = "0.059706",
        user: UUID | None = None,
    ) -> None:
        _query(
            self.url,
            "INSERT INTO protective_stops (id, user_id, execution_attempt_id, allocation_id, "
            "exchange, venue, symbol, position_side, stop_loss_pct, trigger_price, status) "
            "VALUES (:id, :u, :a, :r, 'bybit', 'usdt-m', 'DOGEUSDT.P', :side, :level, :t, "
            ":status)",
            {
                "id": uuid4(),
                "u": user or self.user,
                "a": attempt,
                "r": allocation,
                "side": side,
                "level": Decimal(level),
                "t": None if trigger is None else Decimal(trigger),
                "status": status,
            },
        )


def test_a_pending_stop_is_a_row_with_no_venue_id_yet(at_0040: str) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    assert not _has_table(at_0040, _TABLE)
    _alembic(at_0040, "upgrade", "0041")

    world.stop(allocation, attempt)

    [row] = _query(
        at_0040,
        "SELECT status, position_side, stop_loss_pct, trigger_price, venue_stop_id, "
        "created_at IS NOT NULL, updated_at IS NOT NULL FROM protective_stops",
    )
    assert row == ("PENDING", "LONG", Decimal("10.00"), Decimal("0.059706"), None, True, True)


def test_a_simulated_stop_may_know_no_trigger_price(at_0040: str) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    _alembic(at_0040, "upgrade", "0041")

    world.stop(allocation, attempt, status="SIMULATED", trigger=None)

    assert _query(at_0040, "SELECT status, trigger_price FROM protective_stops") == [
        ("SIMULATED", None)
    ]


@pytest.mark.parametrize("status", _STATUSES)
def test_the_check_takes_each_of_the_six_statuses(at_0040: str, status: str) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    _alembic(at_0040, "upgrade", "0041")

    world.stop(allocation, attempt, status=status)

    assert _query(at_0040, "SELECT status FROM protective_stops") == [(status,)]


@pytest.mark.parametrize("status", ["FIRED", "pending", "", "OPEN"])
def test_the_check_refuses_an_unknown_status(at_0040: str, status: str) -> None:
    """``FIRED`` is SS.7's, which adds it with its own migration."""
    world = World(at_0040)
    allocation, attempt = world.opening()
    _alembic(at_0040, "upgrade", "0041")

    with pytest.raises(DBAPIError) as caught:
        world.stop(allocation, attempt, status=status)

    assert _constraint(caught.value) == _STATUS_CHECK
    assert _query(at_0040, "SELECT count(*) FROM protective_stops") == [(0,)]


@pytest.mark.parametrize(
    ("column", "kwargs", "check"),
    [
        ("position_side", {"side": "FLAT"}, _SIDE_CHECK),
        ("stop_loss_pct", {"level": "0.5"}, _LEVEL_CHECK),
        ("stop_loss_pct", {"level": "50.01"}, _LEVEL_CHECK),
        ("trigger_price", {"trigger": "0"}, _TRIGGER_CHECK),
        ("trigger_price", {"trigger": "-1"}, _TRIGGER_CHECK),
    ],
)
def test_the_checks_refuse_a_side_a_level_or_a_trigger_out_of_range(
    at_0040: str, column: str, kwargs: dict[str, str], check: str
) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    _alembic(at_0040, "upgrade", "0041")

    with pytest.raises(DBAPIError) as caught:
        world.stop(allocation, attempt, **kwargs)  # type: ignore[arg-type]

    assert _constraint(caught.value) == check, column


def test_an_attempt_has_at_most_one_stop(at_0040: str) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    _alembic(at_0040, "upgrade", "0041")
    world.stop(allocation, attempt)

    with pytest.raises(DBAPIError) as caught:
        world.stop(allocation, attempt)

    assert _constraint(caught.value) == _ATTEMPT_UNIQUE


def test_a_stop_names_an_attempt_an_allocation_and_a_user_that_exist(at_0040: str) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    _alembic(at_0040, "upgrade", "0041")

    for args, kwargs, constraint in (
        ((allocation, uuid4()), {}, _ATTEMPT_FK),
        ((uuid4(), attempt), {}, _ALLOCATION_FK),
        ((allocation, attempt), {"user": uuid4()}, _USER_FK),
    ):
        with pytest.raises(DBAPIError) as caught:
            world.stop(*args, **kwargs)  # type: ignore[arg-type]
        assert _constraint(caught.value) == constraint
    assert _query(at_0040, "SELECT count(*) FROM protective_stops") == [(0,)]


def test_the_lookups_the_confirm_job_and_the_watcher_make_have_their_indexes(
    at_0040: str,
) -> None:
    _alembic(at_0040, "upgrade", "0041")

    names = {
        row[0]
        for row in _query(
            at_0040, "SELECT indexname FROM pg_indexes WHERE tablename = 'protective_stops'"
        )
    }

    assert _INDEXES <= names


def test_downgrade_drops_the_table_and_the_upgrade_runs_again(at_0040: str) -> None:
    world = World(at_0040)
    allocation, attempt = world.opening()
    attempts_before = _query(at_0040, "SELECT id, status FROM execution_attempts")
    _alembic(at_0040, "upgrade", "0041")
    world.stop(allocation, attempt)

    _alembic(at_0040, "downgrade", "0040")

    assert not _has_table(at_0040, _TABLE)
    assert _query(at_0040, "SELECT id, status FROM execution_attempts") == attempts_before

    _alembic(at_0040, "upgrade", "0041")

    assert _has_table(at_0040, _TABLE)
    assert _query(at_0040, "SELECT count(*) FROM protective_stops") == [(0,)]


def _constraint(error: DBAPIError) -> str | None:
    """The constraint a write trips, BY NAME, never by message text."""
    return getattr(error.orig.__cause__, "constraint_name", None)  # type: ignore[union-attr]

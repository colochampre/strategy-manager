"""Migration ``0043`` -- why an execution attempt exists, and the ``FIRED`` stop status
(subscriber-safety SS.7).

* ``execution_attempts.cause`` is ``SIGNAL``, ``STOP``, ``SAFETY_CLOSE`` or ``MANUAL``,
  checked by name, NOT NULL.
* Rows written before it are backfilled by rule: a ``signal_id`` gives ``SIGNAL``, a
  ``VENUE`` origin gives ``MANUAL``, a ``SYSTEM`` close with no signal gives
  ``SAFETY_CLOSE`` (SS.5's confirm job), anything else gives ``SIGNAL``. The upgrade prints
  the count per cause, for the rehearsal.
* ``ck_protective_stops_status`` gains ``FIRED``.
* The downgrade refuses while a ``FIRED`` stop or a non-``SIGNAL`` cause exists, instead of
  losing it.

Real PostgreSQL, one database per scenario, seeded at ``0042``.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from tests.migrations.test_0038_strategy_sharing import _BACKEND_DIR, _alembic, _query
from tests.migrations.test_0041_protective_stops import World, _constraint
from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_DB_NAME = "strategy_manager_test_attempt_cause"
_CAUSE_CHECK = "ck_execution_attempts_cause"
_STATUS_CHECK = "ck_protective_stops_status"
_CAUSES = ["SIGNAL", "STOP", "SAFETY_CLOSE", "MANUAL"]


@pytest.fixture
def at_0042() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0042") as url:
        yield url


def _signal(world: World) -> UUID:
    signal = uuid4()
    _query(
        world.url,
        "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
        "contracts, position_size, price, symbol, signal_type) VALUES (:id, :s, :k, "
        "'{}'::jsonb, 'sell', 1, 0, 2, 'DOGEUSDT.P', 'EXIT')",
        {"id": signal, "s": world.strategy, "k": str(uuid4())},
    )
    return signal


def _close(
    world: World, allocation: UUID, *, origin: str = "SYSTEM", signal: UUID | None = None
) -> UUID:
    attempt = uuid4()
    _query(
        world.url,
        "INSERT INTO execution_attempts (id, user_id, closes_allocation_id, exchange, venue, "
        "settlement_currency, symbol, side, quantity, status, origin, client_order_id, "
        "signal_id) VALUES (:id, :u, :a, 'bybit', 'usdt-m', 'USDT', 'DOGEUSDT.P', 'SELL', 76, "
        "'FILLED', :o, :c, :sig)",
        {
            "id": attempt,
            "u": world.user,
            "a": allocation,
            "o": origin,
            "c": str(uuid4()),
            "sig": signal,
        },
    )
    return attempt


def _causes(url: str) -> dict[UUID, str]:
    return {row[0]: row[1] for row in _query(url, "SELECT id, cause FROM execution_attempts")}


def _upgrade_output(url: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0043"],
        cwd=str(_BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": url, "DRY_RUN": "false"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_existing_attempts_are_backfilled_by_rule(at_0042: str) -> None:
    world = World(at_0042)
    with_signal, opening_attempt = world.opening()
    signal = _signal(world)
    _query(
        at_0042,
        "UPDATE execution_attempts SET signal_id = :s WHERE id = :a",
        {"s": signal, "a": opening_attempt},
    )
    no_signal_open, no_signal_open_attempt = world.opening()
    signalled_close = _close(world, with_signal, signal=signal)
    venue_close = _close(world, no_signal_open, origin="VENUE")
    safety_close = _close(world, no_signal_open)

    _alembic(at_0042, "upgrade", "0043")

    assert _causes(at_0042) == {
        opening_attempt: "SIGNAL",  # a signal_id
        no_signal_open_attempt: "SIGNAL",  # anything else
        signalled_close: "SIGNAL",  # a signal_id wins over everything
        venue_close: "MANUAL",  # a reconciliation booking of a trade done by hand
        safety_close: "SAFETY_CLOSE",  # a SYSTEM close with no signal
    }


def test_a_venue_attempt_with_a_signal_is_still_a_signal_by_the_rules_order(
    at_0042: str,
) -> None:
    world = World(at_0042)
    allocation, _ = world.opening()
    close = _close(world, allocation, origin="VENUE", signal=_signal(world))

    _alembic(at_0042, "upgrade", "0043")

    assert _causes(at_0042)[close] == "SIGNAL"


def test_the_upgrade_prints_the_count_per_cause(at_0042: str) -> None:
    world = World(at_0042)
    allocation, _ = world.opening()
    _close(world, allocation)
    _close(world, allocation)
    _close(world, allocation, origin="VENUE")

    output = _upgrade_output(at_0042)

    assert "SIGNAL=1" in output
    assert "MANUAL=1" in output
    assert "SAFETY_CLOSE=2" in output
    assert "STOP=0" in output


def test_a_row_written_after_takes_the_signal_default_until_a_writer_says_otherwise(
    at_0042: str,
) -> None:
    world = World(at_0042)
    _alembic(at_0042, "upgrade", "0043")

    _, attempt = world.opening()

    assert _causes(at_0042) == {attempt: "SIGNAL"}


def test_the_column_is_not_null(at_0042: str) -> None:
    _alembic(at_0042, "upgrade", "0043")

    assert _query(
        at_0042,
        "SELECT is_nullable, data_type FROM information_schema.columns "
        "WHERE table_name = 'execution_attempts' AND column_name = 'cause'",
    ) == [("NO", "text")]


@pytest.mark.parametrize("cause", _CAUSES)
def test_the_check_takes_each_of_the_four_causes(at_0042: str, cause: str) -> None:
    world = World(at_0042)
    allocation, _ = world.opening()
    _alembic(at_0042, "upgrade", "0043")

    close = _close(world, allocation)
    _query(
        at_0042, "UPDATE execution_attempts SET cause = :c WHERE id = :i", {"c": cause, "i": close}
    )

    assert _causes(at_0042)[close] == cause


@pytest.mark.parametrize("cause", ["signal", "", "BOT", "SYSTEM"])
def test_the_check_refuses_an_unknown_cause(at_0042: str, cause: str) -> None:
    world = World(at_0042)
    allocation, _ = world.opening()
    _alembic(at_0042, "upgrade", "0043")
    close = _close(world, allocation)

    with pytest.raises(DBAPIError) as caught:
        _query(
            at_0042,
            "UPDATE execution_attempts SET cause = :c WHERE id = :i",
            {"c": cause, "i": close},
        )

    assert _constraint(caught.value) == _CAUSE_CHECK


def test_a_stop_may_be_fired_only_after_the_migration(at_0042: str) -> None:
    world = World(at_0042)
    allocation, attempt = world.opening()
    with pytest.raises(DBAPIError) as caught:
        world.stop(allocation, attempt, status="FIRED")
    assert _constraint(caught.value) == _STATUS_CHECK

    _alembic(at_0042, "upgrade", "0043")
    world.stop(allocation, attempt, status="FIRED")

    assert _query(at_0042, "SELECT status FROM protective_stops") == [("FIRED",)]


def test_the_status_check_still_refuses_an_unknown_status(at_0042: str) -> None:
    world = World(at_0042)
    allocation, attempt = world.opening()
    _alembic(at_0042, "upgrade", "0043")

    with pytest.raises(DBAPIError) as caught:
        world.stop(allocation, attempt, status="OPEN")

    assert _constraint(caught.value) == _STATUS_CHECK


def test_downgrade_refuses_while_a_fired_stop_exists(at_0042: str) -> None:
    world = World(at_0042)
    allocation, attempt = world.opening()
    _alembic(at_0042, "upgrade", "0043")
    world.stop(allocation, attempt, status="FIRED")

    with pytest.raises(RuntimeError, match="FIRED"):
        _alembic(at_0042, "downgrade", "0042")

    assert _query(at_0042, "SELECT status FROM protective_stops") == [("FIRED",)]


@pytest.mark.parametrize("cause", ["STOP", "SAFETY_CLOSE", "MANUAL"])
def test_downgrade_refuses_while_a_non_signal_cause_exists(at_0042: str, cause: str) -> None:
    world = World(at_0042)
    allocation, _ = world.opening()
    _alembic(at_0042, "upgrade", "0043")
    close = _close(world, allocation)
    _query(
        at_0042, "UPDATE execution_attempts SET cause = :c WHERE id = :i", {"c": cause, "i": close}
    )

    with pytest.raises(RuntimeError, match=cause):
        _alembic(at_0042, "downgrade", "0042")

    assert _causes(at_0042)[close] == cause


def test_downgrade_drops_the_column_and_the_status_and_the_upgrade_runs_again(
    at_0042: str,
) -> None:
    world = World(at_0042)
    allocation, attempt = world.opening()
    world.stop(allocation, attempt, status="RESTING")
    before = _query(at_0042, "SELECT id, status FROM execution_attempts")
    _alembic(at_0042, "upgrade", "0043")

    _alembic(at_0042, "downgrade", "0042")

    assert _query(at_0042, "SELECT id, status FROM execution_attempts") == before
    assert _query(
        at_0042,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'execution_attempts' AND column_name = 'cause'",
    ) == [(0,)]
    with pytest.raises(DBAPIError) as caught:
        _query(at_0042, "UPDATE protective_stops SET status = 'FIRED'")
    assert _constraint(caught.value) == _STATUS_CHECK

    _alembic(at_0042, "upgrade", "0043")

    assert _causes(at_0042) == {attempt: "SIGNAL"}

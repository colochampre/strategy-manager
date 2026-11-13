"""Migration ``0042`` -- the id a Binance stop is placed under (subscriber-safety SS.6).

* ``protective_stops.client_stop_id`` is the ``clientAlgoId`` of the stop, recorded with the
  row BEFORE any algo request, so an unknown outcome can be read back by it.
* It is nullable (a Bybit stop, a simulated one and every row written before this have
  none), and unique where set: two stops never share an id, and any number have none.
* The downgrade drops the column and leaves the rows as they were.

Real PostgreSQL, one database per scenario, seeded at ``0041``.
"""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from tests.migrations.test_0038_strategy_sharing import _alembic, _query
from tests.migrations.test_0041_protective_stops import World, _constraint
from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_DB_NAME = "strategy_manager_test_protective_stop_client_id"
_UNIQUE = "uq_protective_stops_client_stop_id"


@pytest.fixture
def at_0041() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0041") as url:
        yield url


def _columns(url: str) -> dict[str, tuple[str, str]]:
    return {
        row[0]: (row[1], row[2])
        for row in _query(
            url,
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'protective_stops'",
        )
    }


def _stop(world: World, allocation: UUID, attempt: UUID, client_stop_id: str | None) -> None:
    _query(
        world.url,
        "INSERT INTO protective_stops (id, user_id, execution_attempt_id, allocation_id, "
        "exchange, venue, symbol, position_side, stop_loss_pct, trigger_price, status, "
        "client_stop_id) VALUES (:id, :u, :a, :r, 'binance', 'usdt-m', 'DOGEUSDT.P', 'LONG', "
        "10, NULL, 'PENDING', :c)",
        {"id": uuid4(), "u": world.user, "a": attempt, "r": allocation, "c": client_stop_id},
    )


def test_the_column_is_nullable_text_and_rows_written_before_have_none(at_0041: str) -> None:
    world = World(at_0041)
    allocation, attempt = world.opening()
    world.stop(allocation, attempt)
    assert "client_stop_id" not in _columns(at_0041)

    _alembic(at_0041, "upgrade", "0042")

    assert _columns(at_0041)["client_stop_id"] == ("text", "YES")
    assert _query(at_0041, "SELECT client_stop_id FROM protective_stops") == [(None,)]


def test_a_stop_records_the_client_id_it_was_placed_under(at_0041: str) -> None:
    world = World(at_0041)
    allocation, attempt = world.opening()
    _alembic(at_0041, "upgrade", "0042")
    client_stop_id = str(uuid4())

    _stop(world, allocation, attempt, client_stop_id)

    assert _query(at_0041, "SELECT client_stop_id FROM protective_stops") == [(client_stop_id,)]


def test_two_stops_never_share_a_client_id(at_0041: str) -> None:
    world = World(at_0041)
    first, first_attempt = world.opening()
    second, second_attempt = world.opening()
    _alembic(at_0041, "upgrade", "0042")
    client_stop_id = str(uuid4())
    _stop(world, first, first_attempt, client_stop_id)

    with pytest.raises(DBAPIError) as caught:
        _stop(world, second, second_attempt, client_stop_id)

    assert _constraint(caught.value) == _UNIQUE
    assert _query(at_0041, "SELECT count(*) FROM protective_stops") == [(1,)]


def test_any_number_of_stops_may_have_no_client_id(at_0041: str) -> None:
    world = World(at_0041)
    first, first_attempt = world.opening()
    second, second_attempt = world.opening()
    _alembic(at_0041, "upgrade", "0042")

    _stop(world, first, first_attempt, None)
    _stop(world, second, second_attempt, None)

    assert _query(at_0041, "SELECT count(*) FROM protective_stops") == [(2,)]


def test_downgrade_drops_the_column_and_the_upgrade_runs_again(at_0041: str) -> None:
    world = World(at_0041)
    allocation, attempt = world.opening()
    world.stop(allocation, attempt)
    rows_before = _query(at_0041, "SELECT id, status, venue_stop_id FROM protective_stops")
    _alembic(at_0041, "upgrade", "0042")

    _alembic(at_0041, "downgrade", "0041")

    assert "client_stop_id" not in _columns(at_0041)
    assert _query(at_0041, "SELECT id, status, venue_stop_id FROM protective_stops") == rows_before

    _alembic(at_0041, "upgrade", "0042")

    assert "client_stop_id" in _columns(at_0041)

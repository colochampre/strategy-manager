"""Migration ``0048`` -- the seats an author's wider stop lowered (panel-redesign RD.9a).

* ``leverage_lowered_events`` holds one row per lowered seat: the user, the strategy, the
  subscription, the old and the new leverage and when. The leverage goes DOWN and both
  stay in 1..20 (``ck_leverage_lowered_events_lowered``).
* The user, the strategy and the subscription must exist. Deleting the strategy or the seat
  takes its events with it (the seat goes, so does what told its owner about it).
* The panel's read has its index: one user's events, newest first.
* The downgrade drops the table and leaves every other table as it was.

Real PostgreSQL, one database per scenario, seeded at ``0047``.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from tests.migrations.test_0038_strategy_sharing import _alembic, _has_table, _query
from tests.migrations.test_0041_protective_stops import World, _constraint
from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_DB_NAME = "strategy_manager_test_leverage_lowered"
_TABLE = "leverage_lowered_events"
_CHECK = "ck_leverage_lowered_events_lowered"


@pytest.fixture
def at_0047() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0047") as url:
        yield url


def _event(
    world: World,
    *,
    old: int = 10,
    new: int = 6,
    user: object | None = None,
    strategy: object | None = None,
    subscription: object | None = None,
) -> None:
    _query(
        world.url,
        "INSERT INTO leverage_lowered_events (user_id, strategy_id, subscription_id, "
        "old_leverage, new_leverage, occurred_at) VALUES (:u, :s, :sub, :old, :new, now())",
        {
            "u": user or world.user,
            "s": strategy or world.strategy,
            "sub": subscription or world.subscription,
            "old": old,
            "new": new,
        },
    )


def test_an_event_is_a_row_with_its_id_and_both_leverages(at_0047: str) -> None:
    world = World(at_0047)
    assert not _has_table(at_0047, _TABLE)
    _alembic(at_0047, "upgrade", "0048")

    _event(world, old=10, new=6)

    assert _query(
        at_0047, "SELECT old_leverage, new_leverage, id IS NOT NULL FROM leverage_lowered_events"
    ) == [(10, 6, True)]


@pytest.mark.parametrize(
    ("old", "new"), [(6, 6), (6, 10), (21, 6), (10, 0), (0, -1)], ids=str
)
def test_the_check_refuses_a_leverage_that_does_not_go_down_inside_one_to_twenty(
    at_0047: str, old: int, new: int
) -> None:
    world = World(at_0047)
    _alembic(at_0047, "upgrade", "0048")

    with pytest.raises(DBAPIError) as caught:
        _event(world, old=old, new=new)

    assert _constraint(caught.value) == _CHECK
    assert _query(at_0047, "SELECT count(*) FROM leverage_lowered_events") == [(0,)]


def test_the_check_takes_the_widest_drop(at_0047: str) -> None:
    world = World(at_0047)
    _alembic(at_0047, "upgrade", "0048")

    _event(world, old=20, new=1)

    assert _query(at_0047, "SELECT old_leverage, new_leverage FROM leverage_lowered_events") == [
        (20, 1)
    ]


def test_an_event_names_a_user_a_strategy_and_a_subscription_that_exist(at_0047: str) -> None:
    world = World(at_0047)
    _alembic(at_0047, "upgrade", "0048")

    for kwargs, constraint in (
        ({"user": uuid4()}, "fk_leverage_lowered_events_user"),
        ({"strategy": uuid4()}, "fk_leverage_lowered_events_strategy"),
        ({"subscription": uuid4()}, "fk_leverage_lowered_events_subscription"),
    ):
        with pytest.raises(DBAPIError) as caught:
            _event(world, **kwargs)  # type: ignore[arg-type]
        assert _constraint(caught.value) == constraint
    assert _query(at_0047, "SELECT count(*) FROM leverage_lowered_events") == [(0,)]


def test_deleting_the_strategy_takes_its_events_with_it(at_0047: str) -> None:
    world = World(at_0047)
    _alembic(at_0047, "upgrade", "0048")
    _event(world)

    _query(at_0047, "DELETE FROM strategies WHERE id = :s", {"s": world.strategy})

    assert _query(at_0047, "SELECT count(*) FROM leverage_lowered_events") == [(0,)]


def test_the_panels_read_has_its_index(at_0047: str) -> None:
    _alembic(at_0047, "upgrade", "0048")

    [(definition,)] = _query(
        at_0047,
        "SELECT indexdef FROM pg_indexes "
        "WHERE indexname = 'ix_leverage_lowered_events_user_occurred'",
    )

    assert "(user_id, occurred_at DESC)" in definition


def test_downgrade_drops_the_table_and_the_upgrade_runs_again(at_0047: str) -> None:
    world = World(at_0047)
    seats_before = _query(at_0047, "SELECT id, leverage FROM subscriptions")
    _alembic(at_0047, "upgrade", "0048")
    _event(world)

    _alembic(at_0047, "downgrade", "0047")

    assert not _has_table(at_0047, _TABLE)
    assert _query(at_0047, "SELECT id, leverage FROM subscriptions") == seats_before

    _alembic(at_0047, "upgrade", "0048")

    assert _has_table(at_0047, _TABLE)
    assert _query(at_0047, "SELECT count(*) FROM leverage_lowered_events") == [(0,)]

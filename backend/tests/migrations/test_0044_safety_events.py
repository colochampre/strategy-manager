"""Migration ``0044`` -- the safety events a user can read (subscriber-safety SS.10).

* ``safety_events`` holds one row per event: the user, the kind (checked by name, one of
  five), the strategy, the allocation (NULL for a refused opening), the market, when it
  happened and a JSONB detail.
* The source is the execution attempt that booked it or the delivery that was refused: each
  UNIQUE, and exactly one set. The UNIQUE source is what keeps a re-run from writing a
  second row.
* The panel's read has its index: one user's events, newest first.
* The downgrade drops the table and leaves every other table as it was.

Real PostgreSQL, one database per scenario, seeded at ``0043``.
"""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from tests.migrations.test_0038_strategy_sharing import _alembic, _has_table, _query
from tests.migrations.test_0041_protective_stops import World, _constraint
from tests.pg_head_schema import migrated_database

pytestmark = pytest.mark.integration

_DB_NAME = "strategy_manager_test_safety_events"
_TABLE = "safety_events"
_KIND_CHECK = "ck_safety_events_kind"
_SOURCE_CHECK = "ck_safety_events_one_source"
_ATTEMPT_UNIQUE = "uq_safety_events_attempt"
_DELIVERY_UNIQUE = "uq_safety_events_delivery"
_KINDS = [
    "STOP_FIRED",
    "STOP_FAILED_CLOSED",
    "STRATEGY_STOPPED_CLOSED",
    "MANUAL_CLOSE",
    "OPENING_REFUSED_LEVERAGE_CAP",
]


@pytest.fixture
def at_0043() -> Iterator[str]:
    with migrated_database(_DB_NAME, "0043") as url:
        yield url


def _delivery(world: World) -> UUID:
    """A signal and its delivery to the world's subscription."""
    signal = uuid4()
    _query(
        world.url,
        "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, action, "
        "contracts, position_size, price, symbol, signal_type) VALUES (:id, :s, :k, "
        "'{}'::jsonb, 'buy', 1, 1, 2, 'SOLUSDT.P', 'ENTRY')",
        {"id": signal, "s": world.strategy, "k": str(uuid4())},
    )
    delivery = uuid4()
    _query(
        world.url,
        "INSERT INTO signal_deliveries (id, signal_id, subscription_id, user_id) "
        "VALUES (:id, :sig, :sub, :u)",
        {"id": delivery, "sig": signal, "sub": world.subscription, "u": world.user},
    )
    return delivery


def _event(
    world: World,
    *,
    kind: str = "MANUAL_CLOSE",
    allocation: UUID | None = None,
    attempt: UUID | None = None,
    delivery: UUID | None = None,
    user: UUID | None = None,
) -> None:
    _query(
        world.url,
        "INSERT INTO safety_events (user_id, kind, strategy_id, allocation_id, exchange, "
        "venue, symbol, occurred_at, detail, execution_attempt_id, delivery_id) VALUES "
        "(:u, :kind, :s, :alloc, 'bybit', 'usdt-m', 'SOLUSDT', now(), "
        "CAST('{\"quantity\": \"0.5\"}' AS jsonb), :attempt, :delivery)",
        {
            "u": user or world.user,
            "kind": kind,
            "s": world.strategy,
            "alloc": allocation,
            "attempt": attempt,
            "delivery": delivery,
        },
    )


def test_an_event_of_a_booked_order_is_a_row_with_its_detail_and_allocation(
    at_0043: str,
) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    assert not _has_table(at_0043, _TABLE)
    _alembic(at_0043, "upgrade", "0044")

    _event(world, allocation=allocation, attempt=attempt)

    [row] = _query(
        at_0043,
        "SELECT kind, allocation_id, execution_attempt_id, delivery_id, detail ->> 'quantity', "
        "id IS NOT NULL FROM safety_events",
    )
    assert row == ("MANUAL_CLOSE", allocation, attempt, None, "0.5", True)


def test_a_refused_opening_is_an_event_of_its_delivery_with_no_allocation(
    at_0043: str,
) -> None:
    world = World(at_0043)
    _alembic(at_0043, "upgrade", "0044")
    delivery = _delivery(world)

    _event(world, kind="OPENING_REFUSED_LEVERAGE_CAP", delivery=delivery)

    assert _query(
        at_0043, "SELECT kind, allocation_id, execution_attempt_id, delivery_id FROM safety_events"
    ) == [("OPENING_REFUSED_LEVERAGE_CAP", None, None, delivery)]


@pytest.mark.parametrize("kind", _KINDS)
def test_the_check_takes_each_of_the_five_kinds(at_0043: str, kind: str) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    _alembic(at_0043, "upgrade", "0044")

    _event(world, kind=kind, allocation=allocation, attempt=attempt)

    assert _query(at_0043, "SELECT kind FROM safety_events") == [(kind,)]


@pytest.mark.parametrize("kind", ["stop_fired", "", "STOP_GONE"])
def test_the_check_refuses_an_unknown_kind(at_0043: str, kind: str) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    _alembic(at_0043, "upgrade", "0044")

    with pytest.raises(DBAPIError) as caught:
        _event(world, kind=kind, allocation=allocation, attempt=attempt)

    assert _constraint(caught.value) == _KIND_CHECK
    assert _query(at_0043, "SELECT count(*) FROM safety_events") == [(0,)]


def test_an_event_names_exactly_one_source(at_0043: str) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    _alembic(at_0043, "upgrade", "0044")
    delivery = _delivery(world)

    for sources in ({}, {"attempt": attempt, "delivery": delivery}):
        with pytest.raises(DBAPIError) as caught:
            _event(world, allocation=allocation, **sources)  # type: ignore[arg-type]
        assert _constraint(caught.value) == _SOURCE_CHECK
    assert _query(at_0043, "SELECT count(*) FROM safety_events") == [(0,)]


def test_a_source_is_recorded_once(at_0043: str) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    _alembic(at_0043, "upgrade", "0044")
    delivery = _delivery(world)
    _event(world, allocation=allocation, attempt=attempt)
    _event(world, kind="OPENING_REFUSED_LEVERAGE_CAP", delivery=delivery)

    with pytest.raises(DBAPIError) as again_attempt:
        _event(world, allocation=allocation, attempt=attempt)
    with pytest.raises(DBAPIError) as again_delivery:
        _event(world, kind="OPENING_REFUSED_LEVERAGE_CAP", delivery=delivery)

    assert _constraint(again_attempt.value) == _ATTEMPT_UNIQUE
    assert _constraint(again_delivery.value) == _DELIVERY_UNIQUE
    assert _query(at_0043, "SELECT count(*) FROM safety_events") == [(2,)]


def test_an_event_names_a_user_a_strategy_and_a_source_that_exist(at_0043: str) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    _alembic(at_0043, "upgrade", "0044")

    for kwargs, constraint in (
        ({"user": uuid4(), "attempt": attempt}, "fk_safety_events_user"),
        ({"attempt": uuid4()}, "fk_safety_events_attempt"),
        ({"delivery": uuid4()}, "fk_safety_events_delivery"),
        ({"allocation": uuid4(), "attempt": attempt}, "fk_safety_events_allocation"),
    ):
        with pytest.raises(DBAPIError) as caught:
            _event(world, **kwargs)  # type: ignore[arg-type]
        assert _constraint(caught.value) == constraint
    assert _query(at_0043, "SELECT count(*) FROM safety_events") == [(0,)]


def test_the_panels_read_has_its_index(at_0043: str) -> None:
    _alembic(at_0043, "upgrade", "0044")

    [(definition,)] = _query(
        at_0043,
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_safety_events_user_occurred'",
    )

    assert "(user_id, occurred_at DESC)" in definition


def test_downgrade_drops_the_table_and_the_upgrade_runs_again(at_0043: str) -> None:
    world = World(at_0043)
    allocation, attempt = world.opening()
    attempts_before = _query(at_0043, "SELECT id, status FROM execution_attempts")
    _alembic(at_0043, "upgrade", "0044")
    _event(world, allocation=allocation, attempt=attempt)

    _alembic(at_0043, "downgrade", "0043")

    assert not _has_table(at_0043, _TABLE)
    assert _query(at_0043, "SELECT id, status FROM execution_attempts") == attempts_before

    _alembic(at_0043, "upgrade", "0044")

    assert _has_table(at_0043, _TABLE)
    assert _query(at_0043, "SELECT count(*) FROM safety_events") == [(0,)]

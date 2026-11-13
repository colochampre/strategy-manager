"""What the panel's "My subscriptions" and Subscribe rest on (tasks.md F.6), on real
PostgreSQL: ``GET /api/subscriptions/held``, and the refusal of a subscription on a
pool whose key is gone (decision 13).

Each request is made as a user who is not the admin. Deleting a key disables its
pool and keeps the row, so a pool that exists says nothing about a key: only an
enabled one does.
"""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow
from tests.identity_auth import OTHER_HEADERS, act_as, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
ClientFor = Callable[[UUID], AsyncClient]

HELD = "/api/subscriptions/held"

#: A body is an explicit list. Anything added to it has to be added here too.
BODY_KEYS = {
    "id",
    "strategy_id",
    "pool_id",
    "allocation_percent",
    "leverage",
    "status",
    "created_at",
    "left_at",
    "ended_at",
    "strategy_name",
    "author_name",
    "authored",
    "exchange",
    "venue",
    "settlement_currency",
    "strategy_enabled",
    "strategy_uptime",
    "stop_loss_pct",
}


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def client_for(
    pg_session_factory: Factory,  # noqa: F811
) -> AsyncIterator[ClientFor]:
    opened: list[AsyncClient] = []

    def make(user_id: UUID) -> AsyncClient:
        app = create_app()
        act_as(app, user_id)

        async def _session() -> AsyncIterator[AsyncSession]:
            async with pg_session_factory() as session:
                yield session

        app.dependency_overrides[shared_db.get_session] = _session
        api = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=OTHER_HEADERS
        )
        opened.append(api)
        return api

    yield make
    for api in opened:
        await api.aclose()


async def _named(factory: Factory, user_id: UUID) -> str:
    name = f"Author {uuid4().hex[:8]}"
    async with factory() as session:
        await session.execute(
            text("UPDATE users SET display_name = :name WHERE id = :id"),
            {"name": name, "id": user_id},
        )
        await session.commit()
    return name


async def _set(factory: Factory, statement: str, **values: Any) -> None:
    async with factory() as session:
        await session.execute(text(statement), values)
        await session.commit()


async def _held(api: AsyncClient) -> list[dict[str, Any]]:
    response = await api.get(HELD)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


async def _only(api: AsyncClient) -> dict[str, Any]:
    held = await _held(api)
    assert len(held) == 1, held
    return held[0]


async def test_a_subscription_comes_with_what_names_its_strategy(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await seeds.user(pg_session_factory)
    author_name = await _named(pg_session_factory, author)
    subscriber, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(
        pg_session_factory, subscriber, strategy_id, pool or 0, share="30", leverage=7
    )
    await _set(
        pg_session_factory,
        "UPDATE strategies SET name = 'The name' WHERE id = :id",
        id=strategy_id,
    )

    held = await _only(client_for(subscriber))

    assert set(held) == BODY_KEYS
    assert held["strategy_id"] == str(strategy_id)
    assert held["pool_id"] == pool
    assert held["allocation_percent"] == "30"
    assert held["leverage"] == 7
    assert held["status"] == "ACTIVE"
    assert held["strategy_name"] == "The name"
    assert held["author_name"] == author_name
    assert held["authored"] is False
    assert (held["exchange"], held["venue"], held["settlement_currency"]) == seeds.MARKET
    assert held["strategy_enabled"] is True


async def test_a_seat_carries_its_strategys_stop_level_for_the_leverage_cap(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await seeds.user(pg_session_factory)
    await _named(pg_session_factory, author)
    subscriber, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(
        pg_session_factory, author_id=author, stop_loss_pct="12.50"
    )
    await seeds.subscription(
        pg_session_factory, subscriber, strategy_id, pool or 0, share="30", leverage=7
    )

    held = await _only(client_for(subscriber))

    assert held["stop_loss_pct"] == "12.50"


async def test_a_seat_says_whether_its_strategy_runs(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """tasks.md L.1: a seat on another author's strategy shows whether it is taking
    signals, as the author's own card does."""
    author, _ = await seeds.user(pg_session_factory)
    subscriber, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool or 0)
    await _set(
        pg_session_factory, "UPDATE strategies SET enabled = false WHERE id = :id", id=strategy_id
    )

    held = await _only(client_for(subscriber))

    assert held["strategy_enabled"] is False


async def _enabled_ten_days_off_two(factory: Any, strategy_id: UUID) -> datetime:
    """The strategy's whole enablement log: on ten days ago, off from six to four days
    ago, on since. Eight days active; the first enable ten days ago."""
    now = datetime.now(UTC)
    async with factory() as session:
        await session.execute(
            text("DELETE FROM strategy_enablement_events WHERE strategy_id = :id"),
            {"id": strategy_id},
        )
        for days_ago, enabled in ((10, True), (6, False), (4, True)):
            await session.execute(
                text(
                    "INSERT INTO strategy_enablement_events "
                    "(id, strategy_id, enabled, occurred_at, origin) "
                    "VALUES (:id, :strategy, :enabled, :at, 'OBSERVED')"
                ),
                {
                    "id": uuid4(),
                    "strategy": strategy_id,
                    "enabled": enabled,
                    "at": now - timedelta(days=days_ago),
                },
            )
        await session.commit()
    return now - timedelta(days=10)


def _reads_eight_days(uptime: dict[str, Any], first: datetime) -> bool:
    eight = timedelta(days=8).total_seconds()
    return (
        eight <= uptime["seconds"] < eight + 120
        and datetime.fromisoformat(uptime["first_enabled_at"]) == first
        and uptime["baseline"] is False
    )


async def test_a_seat_says_how_long_its_strategy_has_run(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """tasks.md L.1: the days active, for a seat on a strategy off the public list too."""
    author, _ = await seeds.user(pg_session_factory)
    subscriber, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool or 0)
    first = await _enabled_ten_days_off_two(pg_session_factory, strategy_id)

    held = await _only(client_for(subscriber))

    assert _reads_eight_days(held["strategy_uptime"], first), held["strategy_uptime"]


async def test_an_author_with_no_name_yet_reads_as_null(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await seeds.user(pg_session_factory)
    subscriber, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author, named=False)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool or 0)

    held = await _only(client_for(subscriber))

    assert "author_name" in held
    assert held["author_name"] is None


async def test_the_author_of_a_strategy_reads_it_as_authored(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, author, strategy_id, pool or 0)

    held = await _only(client_for(author))

    assert held["authored"] is True


async def test_a_strategy_that_turned_private_still_names_itself_to_its_subscriber(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await seeds.user(pg_session_factory)
    subscriber, pool = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool or 0)
    await _set(
        pg_session_factory,
        "UPDATE strategies SET visibility = 'PRIVATE' WHERE id = :id",
        id=strategy_id,
    )

    held = await _held(client_for(subscriber))

    assert [row["strategy_id"] for row in held] == [str(strategy_id)]


async def test_active_and_leaving_are_held_and_ended_is_not(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await seeds.user(pg_session_factory)
    subscriber, pool = await seeds.user(pg_session_factory)
    active = await seeds.strategy(pg_session_factory, author_id=author)
    leaving = await seeds.strategy(pg_session_factory, author_id=author)
    ended = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, active, pool or 0)
    await seeds.subscription(pg_session_factory, subscriber, leaving, pool or 0, status="LEAVING")
    await seeds.subscription(pg_session_factory, subscriber, ended, pool or 0, status="ENDED")

    held = await _held(client_for(subscriber))

    assert {row["strategy_id"]: row["status"] for row in held} == {
        str(active): "ACTIVE",
        str(leaving): "LEAVING",
    }


async def test_nobody_reads_another_users_subscriptions(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    holder, pool = await seeds.user(pg_session_factory)
    stranger, _ = await seeds.user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory)
    await seeds.subscription(pg_session_factory, holder, strategy_id, pool or 0)

    assert await _held(client_for(stranger)) == []


async def test_each_subscription_names_its_own_strategy_in_a_stable_order(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    subscriber, pool = await seeds.user(pg_session_factory)
    first = await seeds.strategy(pg_session_factory)
    second = await seeds.strategy(pg_session_factory)
    for strategy_id, name, moment in (
        (second, "Second", datetime(2026, 9, 2, tzinfo=UTC)),
        (first, "First", datetime(2026, 9, 1, tzinfo=UTC)),
    ):
        await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool or 0)
        await _set(
            pg_session_factory,
            "UPDATE strategies SET name = :name WHERE id = :id",
            name=name,
            id=strategy_id,
        )
        await _set(
            pg_session_factory,
            "UPDATE subscriptions SET created_at = :moment WHERE strategy_id = :id",
            moment=moment,
            id=strategy_id,
        )

    held = await _held(client_for(subscriber))

    assert [(row["strategy_id"], row["strategy_name"]) for row in held] == [
        (str(first), "First"),
        (str(second), "Second"),
    ]


async def test_a_pool_whose_key_is_gone_takes_no_subscription(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """Decision 13: a user with no key browses and does not subscribe. Deleting a key
    disables its pool and keeps the row, so the row alone would let them in."""
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool = await seeds.user(pg_session_factory)
    await _set(
        pg_session_factory, "UPDATE capital_pools SET enabled = false WHERE id = :id", id=pool
    )

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "25"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "NO_POOL_FOR_MARKET"
    async with pg_session_factory() as session:
        stored = await session.execute(
            select(SubscriptionRow.id).where(SubscriptionRow.user_id == user_id)
        )
        assert stored.all() == []

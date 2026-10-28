"""``StrategyView.subscription``: the SIGNED-IN user's own non-ENDED subscription to
the strategy, or null (tasks.md C.4b), on real PostgreSQL.

Mounted through ``create_app()``. The strategies router is admin-only, so every
request carries the admin's assertion; ``act_as`` then makes ``current_user`` resolve
to the user under test, who is NOT necessarily the admin. That is the cross-user
case: the view of one user never carries another's subscription.
"""

from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, act_as, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
ClientFor = Callable[[UUID], AsyncClient]


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
            transport=ASGITransport(app=app), base_url="http://test", headers=ADMIN_HEADERS
        )
        opened.append(api)
        return api

    yield make
    for api in opened:
        await api.aclose()


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record)


def _shown(subscription: dict[str, Any] | None) -> tuple[Any, ...]:
    assert subscription is not None, "no subscription was served"
    return (
        subscription["strategy_id"],
        subscription["pool_id"],
        subscription["allocation_percent"],
        subscription["status"],
    )


async def test_the_detail_carries_the_signed_in_users_subscription(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id or 0, share="30")

    response = await client_for(user_id).get(f"/api/strategies/{strategy_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert _shown(body.get("subscription")) == (str(strategy_id), pool_id, "30", "ACTIVE")
    assert "allocation_percent" not in body


async def test_another_users_subscription_never_appears_in_this_users_view(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """B holds the only subscription. A has none: A's view of the same strategy
    says null, on the detail and on the list, and B's own view shows B's."""
    strategy_id = await seeds.strategy(pg_session_factory)
    holder, holder_pool = await seeds.user(pg_session_factory)
    bystander, _ = await seeds.user(pg_session_factory)
    await seeds.subscription(
        pg_session_factory, holder, strategy_id, holder_pool or 0, share="55"
    )

    detail = await client_for(bystander).get(f"/api/strategies/{strategy_id}")
    listing = await client_for(bystander).get("/api/strategies")
    held = await client_for(holder).get(f"/api/strategies/{strategy_id}")

    assert detail.status_code == 200
    assert "subscription" in detail.json()
    assert detail.json()["subscription"] is None
    assert [row.get("subscription", "absent") for row in listing.json()] == [None]
    assert _shown(held.json().get("subscription")) == (
        str(strategy_id),
        holder_pool,
        "55",
        "ACTIVE",
    )


async def test_a_leaving_subscription_is_served_and_an_ended_one_is_not(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    leaving_strategy = await seeds.strategy(pg_session_factory)
    ended_strategy = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    await seeds.subscription(
        pg_session_factory, user_id, leaving_strategy, pool_id or 0, status="LEAVING", share="20"
    )
    await seeds.subscription(
        pg_session_factory, user_id, ended_strategy, pool_id or 0, status="ENDED", share="20"
    )
    api = client_for(user_id)

    leaving = await api.get(f"/api/strategies/{leaving_strategy}")
    ended = await api.get(f"/api/strategies/{ended_strategy}")

    assert _shown(leaving.json().get("subscription")) == (
        str(leaving_strategy),
        pool_id,
        "20",
        "LEAVING",
    )
    assert "subscription" in ended.json()
    assert ended.json()["subscription"] is None


async def test_the_list_pairs_each_strategy_with_its_own_subscription_in_one_query(
    pg_engine: AsyncEngine,  # noqa: F811
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    subscribed = await seeds.strategy(pg_session_factory)
    unsubscribed = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    await seeds.subscription(pg_session_factory, user_id, subscribed, pool_id or 0, share="12.5")
    api = client_for(user_id)

    with _captured_sql(pg_engine) as for_two:
        two = await api.get("/api/strategies")
    for _ in range(3):
        await seeds.strategy(pg_session_factory)
    with _captured_sql(pg_engine) as for_five:
        five = await api.get("/api/strategies")

    by_id = {row["id"]: row.get("subscription") for row in two.json()}
    assert _shown(by_id[str(subscribed)]) == (str(subscribed), pool_id, "12.5", "ACTIVE")
    assert by_id[str(unsubscribed)] is None
    assert len(five.json()) == 5
    # ``current_user`` and the auth reads aside, the list costs the same however
    # many strategies it serves: no query per strategy.
    assert len(for_two) == len(for_five)

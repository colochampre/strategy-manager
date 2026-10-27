"""``/api/subscriptions`` against real PostgreSQL (tasks.md C.4a).

Mounted through ``create_app()`` so the ``/api`` prefix is part of what is
proven, with ``get_session`` on a real session. Each request is made as one
user (``act_as``) who is NOT the admin: every route is open to any signed-in
user, and answers that user's own rows only (multi-user design AD8).
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.subscriptions.application.errors import AlreadySubscribed
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)
from tests.identity_auth import OTHER_HEADERS, act_as, sign_in_as_admin
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
    """A client signed in as the given user."""
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


# -- subscribe -------------------------------------------------------------


async def test_subscribing_writes_an_active_subscription_in_the_users_own_pool(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "25.5"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["strategy_id"] == str(strategy_id)
    assert body["pool_id"] == pool_id
    assert body["allocation_percent"] == "25.5"
    assert body["status"] == "ACTIVE"
    stored = await seeds.row_of(pg_session_factory, UUID(body["id"]))
    assert stored.user_id == user_id
    assert stored.strategy_id == strategy_id
    assert stored.pool_id == pool_id
    assert stored.allocation_percent == Decimal("25.5")
    assert stored.status == "ACTIVE"


async def test_an_unknown_strategy_is_a_404_and_writes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    user_id, _ = await seeds.user(pg_session_factory)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(uuid4()), "allocation_percent": "30"},
    )

    assert response.status_code == 404
    assert await seeds.rows(pg_session_factory) == []


async def test_an_archived_strategy_is_a_409_and_writes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory, archived=True)
    user_id, _ = await seeds.user(pg_session_factory)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "30"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRATEGY_ARCHIVED"
    assert await seeds.rows(pg_session_factory) == []


async def test_a_user_without_a_pool_for_the_market_is_a_409_even_if_another_user_has_one(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    await seeds.user(pg_session_factory)  # someone else holds a pool on the market
    user_id, _ = await seeds.user(pg_session_factory, pool=False)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "30"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "NO_POOL_FOR_MARKET"
    assert await seeds.rows(pg_session_factory) == []


@pytest.mark.parametrize("status", ["ACTIVE", "LEAVING"])
async def test_a_live_subscription_to_the_strategy_is_a_409_and_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    status: str,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id, status=status)
    before = await seeds.rows(pg_session_factory)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "30"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "ALREADY_SUBSCRIBED"
    assert await seeds.rows(pg_session_factory) == before


async def test_a_user_who_left_for_good_subscribes_again(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id, status="ENDED")

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "30"},
    )

    assert response.status_code == 201
    assert len(await seeds.rows(pg_session_factory)) == 2


async def test_another_users_subscription_does_not_block_this_user(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    first, first_pool = await seeds.user(pg_session_factory)
    assert first_pool is not None
    await seeds.subscription(pg_session_factory, first, strategy_id, first_pool)
    second, second_pool = await seeds.user(pg_session_factory)

    response = await client_for(second).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "30"},
    )

    assert response.status_code == 201
    assert response.json()["pool_id"] == second_pool


@pytest.mark.parametrize("share", ["0", "-1", "100.01", "abc"])
async def test_an_invalid_share_is_a_422_and_writes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    share: str,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, _ = await seeds.user(pg_session_factory)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": share},
    )

    assert response.status_code == 422
    assert await seeds.rows(pg_session_factory) == []


async def test_the_unique_index_closes_the_race_between_two_subscribes(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two requests both read 'no live subscription' before either writes; the
    second one's INSERT meets ``ux_subscriptions_one_live_per_strategy``."""
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)
    before = await seeds.rows(pg_session_factory)

    async def _nothing_live(self: object, user: UUID, strategy: UUID) -> bool:
        return False

    monkeypatch.setattr(SqlAlchemySubscriptionRepository, "has_live", _nothing_live)

    response = await client_for(user_id).post(
        "/api/subscriptions",
        json={"strategy_id": str(strategy_id), "allocation_percent": "30"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "ALREADY_SUBSCRIBED"
    assert await seeds.rows(pg_session_factory) == before


async def test_the_repository_names_the_lost_race(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    from strategy_manager.strategies.domain.strategy import AllocationPercent
    from strategy_manager.subscriptions.domain.subscription import Subscription

    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)

    async with pg_session_factory() as session:
        with pytest.raises(AlreadySubscribed):
            await SqlAlchemySubscriptionRepository(session).insert(
                Subscription(
                    id=uuid4(),
                    user_id=user_id,
                    strategy_id=strategy_id,
                    pool_id=pool_id,
                    allocation_percent=AllocationPercent(Decimal("10")),
                )
            )


async def test_the_repository_writes_only_the_signed_in_users_row(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    from strategy_manager.strategies.domain.strategy import AllocationPercent
    from strategy_manager.subscriptions.domain.subscription import Subscription

    strategy_id = await seeds.strategy(pg_session_factory)
    owner, owner_pool = await seeds.user(pg_session_factory)
    stranger, _ = await seeds.user(pg_session_factory)
    assert owner_pool is not None
    subscription_id = await seeds.subscription(pg_session_factory, owner, strategy_id, owner_pool)
    before = await seeds.rows(pg_session_factory)

    async with pg_session_factory() as session:
        await SqlAlchemySubscriptionRepository(session).update(
            Subscription(
                id=subscription_id,
                user_id=stranger,
                strategy_id=strategy_id,
                pool_id=owner_pool,
                allocation_percent=AllocationPercent(Decimal("99")),
            )
        )
        await session.commit()

    assert await seeds.rows(pg_session_factory) == before


# -- list ------------------------------------------------------------------


async def test_the_list_shows_only_the_signed_in_users_subscriptions(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    mine, my_pool = await seeds.user(pg_session_factory)
    theirs, their_pool = await seeds.user(pg_session_factory)
    assert my_pool is not None and their_pool is not None
    mine_id = await seeds.subscription(pg_session_factory, mine, strategy_id, my_pool)
    await seeds.subscription(pg_session_factory, theirs, strategy_id, their_pool)

    response = await client_for(mine).get("/api/subscriptions")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(mine_id)]


async def test_the_list_of_a_user_with_none_is_empty(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    user_id, _ = await seeds.user(pg_session_factory)

    response = await client_for(user_id).get("/api/subscriptions")

    assert response.status_code == 200
    assert response.json() == []


# -- leave -----------------------------------------------------------------


async def test_leaving_with_an_open_allocation_is_leaving(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)
    await seeds.open_allocation(pg_session_factory, user_id, strategy_id)

    response = await client_for(user_id).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 200
    assert response.json()["status"] == "LEAVING"
    stored = await seeds.row_of(pg_session_factory, subscription_id)
    assert stored.status == "LEAVING"
    assert stored.left_at is not None
    assert stored.ended_at is None


async def test_leaving_with_a_live_reservation_is_leaving(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)
    await seeds.live_reservation(pg_session_factory, user_id, strategy_id)

    response = await client_for(user_id).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 200
    assert response.json()["status"] == "LEAVING"


async def test_leaving_without_an_open_allocation_ends_the_subscription(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)

    response = await client_for(user_id).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 200
    assert response.json()["status"] == "ENDED"
    stored = await seeds.row_of(pg_session_factory, subscription_id)
    assert stored.status == "ENDED"
    assert stored.ended_at is not None


async def test_another_users_open_allocation_does_not_keep_this_user_leaving(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    mine, my_pool = await seeds.user(pg_session_factory)
    theirs, their_pool = await seeds.user(pg_session_factory)
    assert my_pool is not None and their_pool is not None
    subscription_id = await seeds.subscription(pg_session_factory, mine, strategy_id, my_pool)
    await seeds.subscription(pg_session_factory, theirs, strategy_id, their_pool)
    await seeds.open_allocation(pg_session_factory, theirs, strategy_id)

    response = await client_for(mine).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 200
    assert response.json()["status"] == "ENDED"


async def test_another_users_live_reservation_does_not_keep_this_user_leaving(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    mine, my_pool = await seeds.user(pg_session_factory)
    theirs, their_pool = await seeds.user(pg_session_factory)
    assert my_pool is not None and their_pool is not None
    subscription_id = await seeds.subscription(pg_session_factory, mine, strategy_id, my_pool)
    await seeds.subscription(pg_session_factory, theirs, strategy_id, their_pool)
    await seeds.live_reservation(pg_session_factory, theirs, strategy_id)

    response = await client_for(mine).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 200
    assert response.json()["status"] == "ENDED"


@pytest.mark.parametrize("status", ["LEAVING", "ENDED"])
async def test_leaving_a_subscription_that_is_not_active_is_a_409_and_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    status: str,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(
        pg_session_factory, user_id, strategy_id, pool_id, status=status
    )
    before = await seeds.rows(pg_session_factory)

    response = await client_for(user_id).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "SUBSCRIPTION_NOT_ACTIVE"
    assert await seeds.rows(pg_session_factory) == before


def _pool_lock_key(user_id: UUID) -> LockKey:
    exchange, venue, currency = seeds.MARKET
    pool = PoolKey(
        exchange=Exchange(exchange),
        venue=Venue(venue),
        settlement_currency=Currency(currency),
    )
    return LockKey.from_pool_key(user_id, pool)


async def test_leaving_waits_for_the_users_pool_lock(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """The request blocks while another transaction holds the user's pool lock,
    and goes through once it is released: the leave decides under that lock."""
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)
    key = _pool_lock_key(user_id)

    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(key)
        task = asyncio.create_task(
            client_for(user_id).post(f"/api/subscriptions/{subscription_id}/leave")
        )
        await asyncio.sleep(0.5)
        waiting = not task.done()
        still_active = (await seeds.row_of(pg_session_factory, subscription_id)).status
        await holder.rollback()

    response = await asyncio.wait_for(task, timeout=10)
    assert waiting
    assert still_active == "ACTIVE"
    assert response.status_code == 200


async def test_leaving_does_not_wait_for_another_users_pool_lock(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    mine, my_pool = await seeds.user(pg_session_factory)
    other, _ = await seeds.user(pg_session_factory)
    assert my_pool is not None
    subscription_id = await seeds.subscription(pg_session_factory, mine, strategy_id, my_pool)
    others_key = _pool_lock_key(other)

    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(others_key)
        response = await asyncio.wait_for(
            client_for(mine).post(f"/api/subscriptions/{subscription_id}/leave"), timeout=10
        )
        await holder.rollback()

    assert response.status_code == 200


# -- change the share -------------------------------------------------------


async def test_changing_the_share_of_an_active_subscription(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)

    response = await client_for(user_id).patch(
        f"/api/subscriptions/{subscription_id}", json={"allocation_percent": "42.5"}
    )

    assert response.status_code == 200
    assert response.json()["allocation_percent"] == "42.5"
    stored = await seeds.row_of(pg_session_factory, subscription_id)
    assert stored.allocation_percent == Decimal("42.5")
    assert stored.status == "ACTIVE"


@pytest.mark.parametrize("status", ["LEAVING", "ENDED"])
async def test_changing_the_share_of_a_subscription_that_is_not_active_is_a_409(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    status: str,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(
        pg_session_factory, user_id, strategy_id, pool_id, status=status
    )
    before = await seeds.rows(pg_session_factory)

    response = await client_for(user_id).patch(
        f"/api/subscriptions/{subscription_id}", json={"allocation_percent": "42.5"}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "SUBSCRIPTION_NOT_ACTIVE"
    assert await seeds.rows(pg_session_factory) == before


@pytest.mark.parametrize("share", ["0", "100.5"])
async def test_changing_to_an_invalid_share_is_a_422_and_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    share: str,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    user_id, pool_id = await seeds.user(pg_session_factory)
    assert pool_id is not None
    subscription_id = await seeds.subscription(pg_session_factory, user_id, strategy_id, pool_id)
    before = await seeds.rows(pg_session_factory)

    response = await client_for(user_id).patch(
        f"/api/subscriptions/{subscription_id}", json={"allocation_percent": share}
    )

    assert response.status_code == 422
    assert await seeds.rows(pg_session_factory) == before


# -- another user's subscription (AD8) ---------------------------------------


async def test_leaving_another_users_subscription_is_a_404_and_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    owner, owner_pool = await seeds.user(pg_session_factory)
    stranger, _ = await seeds.user(pg_session_factory)
    assert owner_pool is not None
    subscription_id = await seeds.subscription(pg_session_factory, owner, strategy_id, owner_pool)
    before = await seeds.rows(pg_session_factory)

    response = await client_for(stranger).post(f"/api/subscriptions/{subscription_id}/leave")

    assert response.status_code == 404
    assert await seeds.rows(pg_session_factory) == before


async def test_changing_the_share_of_another_users_subscription_is_a_404_and_changes_nothing(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    strategy_id = await seeds.strategy(pg_session_factory)
    owner, owner_pool = await seeds.user(pg_session_factory)
    stranger, _ = await seeds.user(pg_session_factory)
    assert owner_pool is not None
    subscription_id = await seeds.subscription(pg_session_factory, owner, strategy_id, owner_pool)
    before = await seeds.rows(pg_session_factory)

    response = await client_for(stranger).patch(
        f"/api/subscriptions/{subscription_id}", json={"allocation_percent": "99"}
    )

    assert response.status_code == 404
    assert await seeds.rows(pg_session_factory) == before


async def test_an_unknown_subscription_is_a_404_on_leave_and_on_patch(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    user_id, _ = await seeds.user(pg_session_factory)
    api = client_for(user_id)

    left = await api.post(f"/api/subscriptions/{uuid4()}/leave")
    patched = await api.patch(f"/api/subscriptions/{uuid4()}", json={"allocation_percent": "5"})

    assert left.status_code == 404
    assert patched.status_code == 404

"""``StrategyView.subscribers`` and ``live_subscribers``: the author's total
(tasks.md F.5, decisions 10 and 30), on real PostgreSQL.

``subscribers`` is everyone with an ACTIVE subscription, the author and simulated
subscribers included. ``live_subscribers`` is those in ``LIVE``, the same rule the
public list follows, so it is 0 under the brake. The route stays the author's: the
counts cross users, and only on a strategy its reader authored.

Mounted through ``create_app()``. ``act_as`` makes ``current_user`` resolve to the
user under test, who is not the admin.
"""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.strategies.application.ports import SubscriberCounts
from strategy_manager.strategies.infrastructure.subscribers_adapter import (
    StrategySubscribersAdapter,
)
from tests.identity_auth import ADMIN_HEADERS, act_as, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import seed_snapshot, seed_trade_key
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
ClientFor = Callable[[UUID], AsyncClient]

#: The view is an explicit list. Anything added to it has to be added here too.
VIEW_KEYS = {
    "id",
    "name",
    "description",
    "exchange",
    "venue",
    "settlement_currency",
    "fill_mode",
    "enabled",
    "visibility",
    "share_token",
    "archived_at",
    "allowed_pairs",
    "uptime",
    "subscription",
    "secret_last4",
    "subscribers",
    "live_subscribers",
    "capital",
    "stop_loss_pct",
    "created_at",
}


@pytest.fixture(autouse=True)
def _signed_in_with_the_brake_off(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "dry_run", False)


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


async def _user(
    factory: Factory, mode: str = "LIVE", *, key: bool = True, balance: str | None = None
) -> tuple[UUID, int]:
    """A user with a name, in ``mode``, with their own pool and, unless ``key`` is
    false, a key that can trade on it. The names differ because ``users`` is not
    truncated between tests."""
    user_id, pool_id = await seeds.user(factory)
    assert pool_id is not None
    async with factory() as session:
        await session.execute(
            text("UPDATE users SET mode = :mode, display_name = :name WHERE id = :id"),
            {"mode": mode, "name": f"Author {uuid4().hex[:8]}", "id": user_id},
        )
        if key:
            await seed_trade_key(session, user_id)
        if balance is not None:
            await seed_snapshot(
                session,
                seeds.MARKET,
                total=Decimal(balance),
                available=Decimal(balance) / 2,
                observed_at=datetime(2026, 9, 1, tzinfo=UTC),
                user_id=user_id,
            )
        await session.commit()
    return user_id, pool_id


async def _with_three_seats(factory: Factory) -> tuple[UUID, UUID]:
    """A public strategy held by its author and another user, both ``LIVE``, and by
    a third in simulation: three subscribers, two of them live."""
    author, author_pool = await _user(factory)
    live, live_pool = await _user(factory)
    simulated, simulated_pool = await _user(factory, "SIMULATION")
    strategy_id = await seeds.strategy(factory, author_id=author)
    await seeds.subscription(factory, author, strategy_id, author_pool)
    await seeds.subscription(factory, live, strategy_id, live_pool)
    await seeds.subscription(factory, simulated, strategy_id, simulated_pool)
    return author, strategy_id


def _counts(row: dict[str, Any]) -> tuple[Any, Any]:
    return row.get("subscribers"), row.get("live_subscribers")


async def _listed(api: AsyncClient) -> dict[str, dict[str, Any]]:
    response = await api.get("/api/strategies")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()}


async def test_the_total_counts_every_active_subscription_and_live_only_the_live_ones(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, strategy_id = await _with_three_seats(pg_session_factory)

    listed = await _listed(client_for(author))

    assert _counts(listed[str(strategy_id)]) == (3, 2)


async def test_a_strategy_nobody_holds_answers_zero_and_not_a_missing_field(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await _user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)

    listed = await _listed(client_for(author))

    assert _counts(listed[str(strategy_id)]) == (0, 0)


async def test_the_author_is_counted_only_when_they_hold_a_subscription(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await _user(pg_session_factory)
    subscriber, pool = await _user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool)

    listed = await _listed(client_for(author))

    assert _counts(listed[str(strategy_id)]) == (1, 1)


@pytest.mark.parametrize("status", ["LEAVING", "ENDED"])
async def test_a_subscription_that_opens_nothing_counts_for_neither(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    status: str,
) -> None:
    author, _ = await _user(pg_session_factory)
    going, going_pool = await _user(pg_session_factory)
    staying, staying_pool = await _user(pg_session_factory, "SIMULATION")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, going, strategy_id, going_pool, status=status)
    await seeds.subscription(pg_session_factory, staying, strategy_id, staying_pool)

    listed = await _listed(client_for(author))

    assert _counts(listed[str(strategy_id)]) == (1, 0)


async def test_under_the_brake_nobody_trades_live_and_the_total_stays(
    monkeypatch: pytest.MonkeyPatch,
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, strategy_id = await _with_three_seats(pg_session_factory)
    monkeypatch.setattr(get_settings(), "dry_run", True)

    listed = await _listed(client_for(author))

    assert _counts(listed[str(strategy_id)]) == (3, 0)


async def test_each_strategy_shows_its_own_counts(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """Read from the list: a test that asks about one strategy at a time could not
    see a row filed under the wrong one."""
    author, busy = await _with_three_seats(pg_session_factory)
    subscriber, pool = await _user(pg_session_factory, "SIMULATION")
    other = await seeds.strategy(pg_session_factory, author_id=author)
    quiet = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, other, pool)

    listed = await _listed(client_for(author))

    assert {strategy: _counts(row) for strategy, row in listed.items()} == {
        str(busy): (3, 2),
        str(other): (1, 0),
        str(quiet): (0, 0),
    }


async def test_the_detail_and_a_write_answer_the_same_counts(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """Every answer carrying a strategy has one shape, so a page refreshed from a
    write's answer never loses the counts."""
    author, strategy_id = await _with_three_seats(pg_session_factory)
    api = client_for(author)

    detail = await api.get(f"/api/strategies/{strategy_id}")
    renamed = await api.patch(f"/api/strategies/{strategy_id}", json={"name": "Renamed"})

    assert detail.status_code == 200, detail.text
    assert renamed.status_code == 200, renamed.text
    assert _counts(detail.json()) == (3, 2)
    assert _counts(renamed.json()) == (3, 2)


async def test_the_detail_also_follows_the_brake(
    monkeypatch: pytest.MonkeyPatch,
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, strategy_id = await _with_three_seats(pg_session_factory)
    monkeypatch.setattr(get_settings(), "dry_run", True)

    detail = await client_for(author).get(f"/api/strategies/{strategy_id}")

    assert _counts(detail.json()) == (3, 0)


async def test_the_answer_says_how_many_and_nothing_of_anyone(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await _user(pg_session_factory)
    subscriber, pool = await _user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool)
    async with pg_session_factory() as session:
        found = await session.execute(
            text("SELECT email, display_name FROM users WHERE id = :id"), {"id": subscriber}
        )
        email, name = found.one()

    response = await client_for(author).get(f"/api/strategies/{strategy_id}")

    assert set(response.json()) == VIEW_KEYS
    assert response.json()["subscription"] is None
    assert email not in response.text
    assert name not in response.text


async def test_the_author_reads_when_the_strategy_was_made(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    """tasks.md L.1: My strategies sorts by age, so the list says it."""
    author, _ = await _user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET created_at = '2026-09-01T12:00:00Z' WHERE id = :id"),
            {"id": strategy_id},
        )
        await session.commit()

    listed = await _listed(client_for(author))
    detail = await client_for(author).get(f"/api/strategies/{strategy_id}")

    assert listed[str(strategy_id)]["created_at"] == "2026-09-01T12:00:00Z"
    assert detail.json()["created_at"] == "2026-09-01T12:00:00Z"


async def test_a_subscriber_never_reads_the_counts_of_a_strategy_they_did_not_author(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, _ = await _user(pg_session_factory)
    subscriber, pool = await _user(pg_session_factory)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool)
    api = client_for(subscriber)

    assert await _listed(api) == {}
    assert (await api.get(f"/api/strategies/{strategy_id}")).status_code == 404


async def test_the_read_reaches_only_the_strategies_it_was_asked_about(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """Another author's strategy in the same table stays out of the statement, not
    merely out of the answer."""
    _, asked = await _with_three_seats(pg_session_factory)
    _, other = await _with_three_seats(pg_session_factory)
    async with pg_session_factory() as session:
        ledger = SqlAlchemyLedgerRepository(session)
        adapter = StrategySubscribersAdapter(session, ledger, ReadSymbolHoldings(ledger))

        counts = await adapter.counts([asked])

    assert other not in counts
    assert counts == {asked: SubscriberCounts(3, 2)}


@pytest.mark.parametrize(("brake", "live"), [(False, 2), (True, 0)])
async def test_the_author_and_the_public_list_agree_on_who_trades_live(
    monkeypatch: pytest.MonkeyPatch,
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    brake: bool,
    live: int,
) -> None:
    """The same rule is read in two statements, one per module. This is what keeps
    them one rule: a leaving subscriber and a simulated one sit beside the live."""
    author, strategy_id = await _with_three_seats(pg_session_factory)
    leaving, leaving_pool = await _user(pg_session_factory)
    await seeds.subscription(
        pg_session_factory, leaving, strategy_id, leaving_pool, status="LEAVING"
    )
    keyless, keyless_pool = await _user(pg_session_factory, key=False)
    await seeds.subscription(pg_session_factory, keyless, strategy_id, keyless_pool)
    monkeypatch.setattr(get_settings(), "dry_run", brake)
    api = client_for(author)

    listed = await _listed(api)
    public = await api.get(f"/api/public/strategies/{strategy_id}")

    assert public.status_code == 200, public.text
    assert public.json()["live_subscribers"] == live
    assert listed[str(strategy_id)]["live_subscribers"] == live


# --- the capital (decisions 10 and 30, tasks.md G.3) --------------------------------


async def _held_by_two_with_money(
    factory: Factory, *, visibility: str = "PUBLIC"
) -> tuple[UUID, UUID]:
    """The author at 10 % of 1000, a subscriber at 50 % of 400 and a simulated one
    whose balance must not count: 300."""
    author, author_pool = await _user(factory, balance="1000")
    live, live_pool = await _user(factory, balance="400")
    simulated, simulated_pool = await _user(factory, "SIMULATION", balance="9000")
    strategy_id = await seeds.strategy(factory, author_id=author, visibility=visibility)
    await seeds.subscription(factory, author, strategy_id, author_pool, share="10")
    await seeds.subscription(factory, live, strategy_id, live_pool, share="50")
    await seeds.subscription(factory, simulated, strategy_id, simulated_pool, share="50")
    return author, strategy_id


@pytest.mark.parametrize("visibility", ["PUBLIC", "PRIVATE"])
async def test_an_author_reads_the_capital_of_their_strategy_private_or_not(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
    visibility: str,
) -> None:
    author, strategy_id = await _held_by_two_with_money(
        pg_session_factory, visibility=visibility
    )

    listed = await _listed(client_for(author))

    assert Decimal(listed[str(strategy_id)]["capital"]) == Decimal("300")


async def test_each_strategy_shows_its_own_capital_and_nobody_live_adds_up_to_zero(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, held = await _held_by_two_with_money(pg_session_factory)
    quiet = await seeds.strategy(pg_session_factory, author_id=author)

    listed = await _listed(client_for(author))

    assert {strategy: Decimal(row["capital"]) for strategy, row in listed.items()} == {
        str(held): Decimal("300"),
        str(quiet): Decimal(0),
    }


async def test_the_detail_and_a_write_answer_the_same_capital(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, strategy_id = await _held_by_two_with_money(pg_session_factory)
    api = client_for(author)

    detail = await api.get(f"/api/strategies/{strategy_id}")
    renamed = await api.patch(f"/api/strategies/{strategy_id}", json={"name": "Renamed"})

    assert Decimal(detail.json()["capital"]) == Decimal("300")
    assert Decimal(renamed.json()["capital"]) == Decimal("300")


async def test_under_the_brake_the_authors_capital_is_null(
    monkeypatch: pytest.MonkeyPatch,
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, strategy_id = await _held_by_two_with_money(pg_session_factory)
    monkeypatch.setattr(get_settings(), "dry_run", True)
    api = client_for(author)

    listed = await _listed(api)
    detail = await api.get(f"/api/strategies/{strategy_id}")

    assert listed[str(strategy_id)]["capital"] is None
    assert detail.json()["capital"] is None


async def test_the_author_and_the_public_list_read_one_capital(
    pg_session_factory: Factory,  # noqa: F811
    client_for: ClientFor,
) -> None:
    author, strategy_id = await _held_by_two_with_money(pg_session_factory)
    api = client_for(author)

    listed = await _listed(api)
    public = await api.get(f"/api/public/strategies/{strategy_id}")

    assert public.json()["capital"] == listed[str(strategy_id)]["capital"]

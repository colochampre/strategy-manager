"""``GET /api/public/strategies`` and ``GET /api/public/strategies/{id}``: the one
read that crosses users on purpose (tasks.md F.4, decisions 15, 27, 28 and 30)
[DB].

Each test goes through the application's route over real PostgreSQL, ORM schema.
A symbol is stored in the spelling each alert carried, and a chain is one exact
spelling (tasks.md F.3).
"""

import ast
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import strategy_manager
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.signals.infrastructure.models import SignalRow
from tests.identity_auth import ADMIN_HEADERS, OTHER_HEADERS, seed_admin, sign_in_as_admin
from tests.ledger.infrastructure.conftest import seed_strategy
from tests.owner import seed_other_user, seed_pool, seed_snapshot

MARKET = ("bybit", "usdt-m", "USDT")
OTHER_MARKET = ("bybit", "spot", "USDT")
T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)
LIST = "/api/public/strategies"
ROUTER_LOGGER = "strategy_manager.performance.infrastructure.public_strategies_router"

#: A body is an explicit list. Anything added to it has to be added here too.
BODY_KEYS = {
    "id",
    "name",
    "author_name",
    "exchange",
    "venue",
    "settlement_currency",
    "created_at",
    "closed_trade_count",
    "unleveraged_return_before_fees",
    "live_subscribers",
    "capital",
}

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _signed_in_with_the_brake_off(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "dry_run", False)


async def _new_user(
    factory: Factory, *, name: str | None = "generated", mode: str = "LIVE"
) -> UUID:
    async with factory() as session:
        user = await seed_other_user(session)
        await session.execute(
            text("UPDATE users SET mode = :mode, display_name = :name WHERE id = :id"),
            {
                "mode": mode,
                "name": f"Author {user.hex[:8]}" if name == "generated" else name,
                "id": user,
            },
        )
        await session.commit()
    return user


async def _strategy(
    factory: Factory,
    author: UUID,
    *,
    visibility: str = "PUBLIC",
    archived: bool = False,
    created_at: datetime = T0,
) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(
        factory, strategy_id=strategy_id, author_id=author, enabled=not archived
    )
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE strategies SET visibility = :visibility, archived_at = :archived, "
                "created_at = :created_at WHERE id = :id"
            ),
            {
                "visibility": visibility,
                "archived": T0 if archived else None,
                "created_at": created_at,
                "id": strategy_id,
            },
        )
        await session.commit()
    return strategy_id


async def _signal(
    factory: Factory,
    strategy_id: UUID,
    *,
    symbol: str = "STXUSDT.P",
    position_size: str,
    price: str,
    at: datetime,
    status: str = "PROCESSED",
    signal_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with factory() as session:
        session.add(
            SignalRow(
                id=signal_id or uuid4(),
                strategy_id=strategy_id,
                idempotency_key=idempotency_key or str(uuid4()),
                raw_payload={},
                received_at=at,
                status=status,
                action="buy",
                contracts=Decimal("1"),
                position_size=Decimal(position_size),
                price=Decimal(price),
                symbol=symbol,
                signal_type="strategy",
                outcome_reason="A_REFUSAL" if status == "REJECTED" else None,
                decided_at=at,
            )
        )
        await session.commit()


async def _subscribe(
    factory: Factory,
    user: UUID,
    strategy_id: UUID,
    *,
    share: str,
    total: str | None,
    status: str = "ACTIVE",
) -> UUID:
    """``user``'s subscription through a pool of their own on ``MARKET``. Half the
    balance is free, so a read of ``available`` instead of the total shows."""
    subscription = uuid4()
    async with factory() as session:
        pool = await seed_pool(session, MARKET, user_id=user)
        if total is not None:
            await seed_snapshot(
                session,
                MARKET,
                total=Decimal(total),
                available=Decimal(total) / 2,
                observed_at=T0,
                user_id=user,
            )
        await session.execute(
            text(
                "INSERT INTO subscriptions "
                "(id, user_id, strategy_id, pool_id, allocation_percent, status) "
                "VALUES (:id, :user, :strategy, :pool, :share, :status)"
            ),
            {
                "id": subscription,
                "user": user,
                "strategy": strategy_id,
                "pool": pool,
                "share": Decimal(share),
                "status": status,
            },
        )
        await session.commit()
    return subscription


@dataclass(frozen=True, slots=True)
class _Api:
    factory: Factory

    async def get(self, path: str, headers: dict[str, str] = ADMIN_HEADERS) -> Response:
        app = create_app()

        async def _session() -> AsyncIterator[AsyncSession]:
            async with self.factory() as session:
                yield session

        app.dependency_overrides[shared_db.get_session] = _session
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)

    async def listed(self) -> list[dict[str, Any]]:
        response = await self.get(LIST)
        assert response.status_code == 200, response.text
        body: list[dict[str, Any]] = response.json()
        return body

    async def page(self, strategy_id: UUID) -> dict[str, Any]:
        response = await self.get(f"{LIST}/{strategy_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body


@pytest.fixture
def api(pg_session_factory: Factory) -> _Api:
    return _Api(pg_session_factory)


# --- what a strategy shows ------------------------------------------------------------


async def test_a_public_strategy_shows_exactly_the_listed_fields(
    pg_session_factory: Factory, api: _Api
) -> None:
    chosen = f"Ana {uuid4().hex[:8]}"
    author = await _new_user(pg_session_factory, name=chosen)
    strategy_id = await _strategy(pg_session_factory, author)

    [listed] = await api.listed()

    assert set(listed) == BODY_KEYS
    assert listed["id"] == str(strategy_id)
    assert listed["name"] == f"strategy-{strategy_id}"
    assert listed["author_name"] == chosen
    assert (listed["exchange"], listed["venue"]) == ("bybit", "usdt-m")
    assert listed["settlement_currency"] == "USDT"
    assert listed["created_at"] == "2026-09-01T12:00:00Z"


async def test_the_page_says_what_the_list_says(pg_session_factory: Factory, api: _Api) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _subscribe(pg_session_factory, author, strategy_id, share="50", total="1000")
    await _signal(
        pg_session_factory, strategy_id, position_size="1", price="100", at=T0
    )
    await _signal(
        pg_session_factory,
        strategy_id,
        position_size="0",
        price="110",
        at=T0 + timedelta(hours=1),
    )

    [listed] = await api.listed()

    assert await api.page(strategy_id) == listed
    assert listed["closed_trade_count"] == 1


async def test_the_list_runs_oldest_first_and_its_ties_are_stable(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    newer = await _strategy(pg_session_factory, author, created_at=T0 + timedelta(days=2))
    tied = [
        await _strategy(pg_session_factory, author, created_at=T0 + timedelta(days=1))
        for _ in range(3)
    ]
    older = await _strategy(pg_session_factory, author, created_at=T0)

    order = [each["id"] for each in await api.listed()]

    expected = [older, *sorted(tied), newer]
    assert order == [str(each) for each in expected]


async def test_no_signal_read_answers_zero_trades_and_zero_return(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)

    listed = await api.page(strategy_id)

    assert listed["closed_trade_count"] == 0
    assert Decimal(listed["unleveraged_return_before_fees"]) == 0


# --- the record -----------------------------------------------------------------------


async def test_the_record_reads_every_stored_signal_whatever_its_status(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _signal(
        pg_session_factory,
        strategy_id,
        position_size="1",
        price="100",
        at=T0,
        status="REJECTED",
    )
    await _signal(
        pg_session_factory,
        strategy_id,
        position_size="0",
        price="110",
        at=T0 + timedelta(hours=1),
        status="ACCEPTED",
    )

    listed = await api.page(strategy_id)

    assert listed["closed_trade_count"] == 1
    assert listed["unleveraged_return_before_fees"] == "0.1000000000"


async def test_each_spelling_keeps_its_chain_and_an_open_trade_counts_for_nothing(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    day = timedelta(days=1)
    await _signal(
        pg_session_factory, strategy_id, symbol="STXUSDT.P", position_size="1", price="100", at=T0
    )
    await _signal(
        pg_session_factory,
        strategy_id,
        symbol="STXUSDT",
        position_size="0",
        price="500",
        at=T0 + timedelta(hours=1),
    )
    await _signal(
        pg_session_factory,
        strategy_id,
        symbol="STXUSDT.P",
        position_size="0",
        price="110",
        at=T0 + day,
    )
    await _signal(
        pg_session_factory,
        strategy_id,
        symbol="ETHUSDT.P",
        position_size="1",
        price="2000",
        at=T0 + day,
    )

    listed = await api.page(strategy_id)

    assert listed["closed_trade_count"] == 1
    assert listed["unleveraged_return_before_fees"] == "0.1000000000"


async def test_two_signals_of_one_instant_read_in_the_order_of_their_ids(
    pg_session_factory: Factory, api: _Api
) -> None:
    """The close is stored first and its idempotency key sorts first, so a table
    scan and an index scan both meet it first. Only the read's ``id`` tiebreak
    gives one closed trade."""
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _signal(
        pg_session_factory,
        strategy_id,
        position_size="0",
        price="110",
        at=T0,
        signal_id=UUID("00000000-0000-4000-8000-000000000002"),
        idempotency_key="a-close",
    )
    await _signal(
        pg_session_factory,
        strategy_id,
        position_size="1",
        price="100",
        at=T0,
        signal_id=UUID("00000000-0000-4000-8000-000000000001"),
        idempotency_key="b-open",
    )

    assert (await api.page(strategy_id))["closed_trade_count"] == 1


async def test_a_record_is_its_own_strategys(pg_session_factory: Factory, api: _Api) -> None:
    """Read through the list, where one statement answers for every strategy.
    The older strategy is the quiet one, so a record filed under the first id
    asked about would land on it."""
    author = await _new_user(pg_session_factory)
    quiet = await _strategy(pg_session_factory, author, created_at=T0)
    traded = await _strategy(pg_session_factory, author, created_at=T0 + timedelta(days=1))
    await _signal(pg_session_factory, traded, position_size="1", price="100", at=T0)
    await _signal(
        pg_session_factory, traded, position_size="0", price="110", at=T0 + timedelta(hours=1)
    )

    counts = {each["id"]: each["closed_trade_count"] for each in await api.listed()}

    assert counts == {str(quiet): 0, str(traded): 1}


# --- who trades it live ---------------------------------------------------------------


async def test_the_capital_adds_everyone_live_and_the_author_counts(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    subscriber = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _subscribe(pg_session_factory, author, strategy_id, share="10", total="1000")
    await _subscribe(pg_session_factory, subscriber, strategy_id, share="50", total="400")

    listed = await api.page(strategy_id)

    assert listed["live_subscribers"] == 2
    assert Decimal(listed["capital"]) == Decimal("300")


async def test_a_seat_reads_the_balance_of_its_own_pool_only(
    pg_session_factory: Factory, api: _Api
) -> None:
    """The subscriber's other pool holds a bigger balance, and it joins nothing."""
    subscriber = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, await _new_user(pg_session_factory))
    await _subscribe(pg_session_factory, subscriber, strategy_id, share="50", total="400")
    async with pg_session_factory() as session:
        await seed_pool(session, OTHER_MARKET, user_id=subscriber)
        await seed_snapshot(
            session,
            OTHER_MARKET,
            total=Decimal("9000"),
            available=Decimal("9000"),
            observed_at=T0,
            user_id=subscriber,
        )
        await session.commit()

    listed = await api.page(strategy_id)

    assert listed["live_subscribers"] == 1
    assert Decimal(listed["capital"]) == Decimal("200")


@pytest.mark.parametrize("status", ["LEAVING", "ENDED"])
async def test_a_subscription_on_its_way_out_is_not_trading_live(
    status: str, pg_session_factory: Factory, api: _Api
) -> None:
    strategy_id = await _strategy(pg_session_factory, await _new_user(pg_session_factory))
    leaving = await _new_user(pg_session_factory)
    await _subscribe(
        pg_session_factory, leaving, strategy_id, share="50", total="400", status=status
    )

    listed = await api.page(strategy_id)

    assert listed["live_subscribers"] == 0
    assert Decimal(listed["capital"]) == 0


async def test_a_simulated_subscriber_shows_no_money_at_no_risk(
    pg_session_factory: Factory, api: _Api
) -> None:
    strategy_id = await _strategy(pg_session_factory, await _new_user(pg_session_factory))
    simulating = await _new_user(pg_session_factory, mode="SIMULATION")
    await _subscribe(pg_session_factory, simulating, strategy_id, share="50", total="400")

    listed = await api.page(strategy_id)

    assert listed["live_subscribers"] == 0
    assert Decimal(listed["capital"]) == 0


async def test_a_pool_with_no_balance_read_counts_the_seat_and_adds_no_money(
    pg_session_factory: Factory, api: _Api
) -> None:
    strategy_id = await _strategy(pg_session_factory, await _new_user(pg_session_factory))
    unsynced = await _new_user(pg_session_factory)
    await _subscribe(pg_session_factory, unsynced, strategy_id, share="50", total=None)

    listed = await api.page(strategy_id)

    assert listed["live_subscribers"] == 1
    assert Decimal(listed["capital"]) == 0


async def test_under_the_brake_nobody_trades_live_and_the_capital_is_null(
    pg_session_factory: Factory, api: _Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", True)
    author = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    await _subscribe(pg_session_factory, author, strategy_id, share="50", total="400")

    listed = await api.page(strategy_id)

    assert listed["live_subscribers"] == 0
    assert listed["capital"] is None


async def test_a_capital_is_its_own_strategys(pg_session_factory: Factory, api: _Api) -> None:
    """Read through the list, as a record is: the older strategy holds nobody."""
    author = await _new_user(pg_session_factory)
    empty = await _strategy(pg_session_factory, author, created_at=T0)
    held = await _strategy(pg_session_factory, author, created_at=T0 + timedelta(days=1))
    await _subscribe(pg_session_factory, author, held, share="50", total="400")

    capitals = {each["id"]: Decimal(each["capital"]) for each in await api.listed()}

    assert capitals == {str(empty): Decimal(0), str(held): Decimal("200")}


# --- nothing private reaches a body ---------------------------------------------------


async def test_no_body_carries_an_id_an_email_a_secret_hint_or_a_subscriber_row(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    subscriber = await _new_user(pg_session_factory)
    strategy_id = await _strategy(pg_session_factory, author)
    author_seat = await _subscribe(
        pg_session_factory, author, strategy_id, share="10", total="1000"
    )
    seat = await _subscribe(pg_session_factory, subscriber, strategy_id, share="50", total="400")
    async with pg_session_factory() as session:
        emails = (
            await session.execute(
                text("SELECT email FROM users WHERE id IN (:author, :subscriber)"),
                {"author": author, "subscriber": subscriber},
            )
        ).scalars().all()
        await session.execute(
            text("UPDATE strategies SET allowed_pairs = ARRAY['DOGEUSDT'] WHERE id = :id"),
            {"id": strategy_id},
        )
        await session.commit()
    assert len(emails) == 2

    for response in (await api.get(LIST), await api.get(f"{LIST}/{strategy_id}")):
        assert response.status_code == 200
        for private in (
            str(author),
            str(subscriber),
            str(author_seat),
            str(seat),
            *emails,
            "@",
            "cret",  # the fixture's webhook_secret_last4
            "webhook",
            "secret",
            "DOGEUSDT",
            "allocation_percent",
            "author_id",
            "user_id",
            "enabled",
        ):
            assert private not in response.text, private


# --- who is on the list ---------------------------------------------------------------


async def _not_listed(factory: Factory, author: UUID) -> dict[str, UUID]:
    unnamed = await _new_user(factory, name=None)
    return {
        "private": await _strategy(factory, author, visibility="PRIVATE"),
        "archived": await _strategy(factory, author, archived=True),
        "unnamed author": await _strategy(factory, unnamed),
    }


async def _every_row(factory: Factory) -> list[list[Any]]:
    tables = (
        "strategies",
        "subscriptions",
        "signals",
        "capital_pools",
        "pool_balance_snapshots",
        "signal_deliveries",
        "reservations",
        "jobs",
    )
    rows: list[list[Any]] = []
    async with factory() as session:
        for table in tables:
            found = await session.execute(
                text(f"SELECT to_jsonb(t)::text AS row FROM {table} t ORDER BY 1")  # noqa: S608
            )
            rows.append([table, *found.scalars().all()])
        users = await session.execute(
            text("SELECT id, email, mode, display_name FROM users ORDER BY id")
        )
        rows.append(["users", *[str(row) for row in users.all()]])
    return rows


async def test_the_list_leaves_out_private_archived_and_unnamed_authors(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    await _not_listed(pg_session_factory, author)
    public = await _strategy(pg_session_factory, author)

    assert [each["id"] for each in await api.listed()] == [str(public)]


@pytest.mark.parametrize("case", ["private", "archived", "unnamed author"])
async def test_another_user_gets_a_404_a_stranger_cannot_tell_from_no_strategy_and_no_row_changes(
    case: str, pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    target = (await _not_listed(pg_session_factory, author))[case]
    await _subscribe(pg_session_factory, author, target, share="50", total="400")
    # The stranger's own row is written at their first request.
    await api.get(LIST, OTHER_HEADERS)
    before = await _every_row(pg_session_factory)

    response = await api.get(f"{LIST}/{target}", OTHER_HEADERS)
    unknown = await api.get(f"{LIST}/{uuid4()}", OTHER_HEADERS)

    assert response.status_code == 404
    assert response.json() == unknown.json()
    assert await _every_row(pg_session_factory) == before


async def test_the_author_of_a_strategy_off_the_list_gets_the_same_404(
    pg_session_factory: Factory, api: _Api
) -> None:
    async with pg_session_factory() as session:
        admin = await seed_admin(session)
        await session.commit()
    private = await _strategy(pg_session_factory, admin, visibility="PRIVATE")

    response = await api.get(f"{LIST}/{private}", ADMIN_HEADERS)

    assert response.status_code == 404


async def _crafted_record(factory: Factory, strategy_id: UUID) -> None:
    """Two days of the widest prices a signal can hold (tasks.md G.1). An alert's
    price is whatever its sender writes, and compounded this return needs more
    digits than the wire can round."""
    for day in range(2):
        opened = T0 + timedelta(days=day)
        await _signal(
            factory, strategy_id, position_size="1", price="0.000000000000000001", at=opened
        )
        await _signal(
            factory,
            strategy_id,
            position_size="0",
            price="99999999999999999999",
            at=opened + timedelta(hours=1),
        )


async def test_one_strategy_the_wire_cannot_write_leaves_the_rest_of_the_list(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    crafted = await _strategy(pg_session_factory, author, created_at=T0)
    honest = await _strategy(pg_session_factory, author, created_at=T0 + timedelta(hours=1))
    await _crafted_record(pg_session_factory, crafted)

    response = await api.get(LIST)

    assert response.status_code == 200
    assert [each["id"] for each in response.json()] == [str(honest)]


async def test_the_page_of_a_strategy_the_wire_cannot_write_answers_as_off_the_list(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    crafted = await _strategy(pg_session_factory, author)
    await _crafted_record(pg_session_factory, crafted)

    response = await api.get(f"{LIST}/{crafted}")
    unknown = await api.get(f"{LIST}/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == unknown.json()


async def test_a_strategy_left_out_for_its_return_says_so_in_the_log(
    pg_session_factory: Factory, api: _Api, caplog: pytest.LogCaptureFixture
) -> None:
    author = await _new_user(pg_session_factory)
    crafted = await _strategy(pg_session_factory, author)
    await _crafted_record(pg_session_factory, crafted)

    with caplog.at_level("WARNING", logger=ROUTER_LOGGER):
        await api.get(LIST)

    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == ROUTER_LOGGER and str(crafted) in record.getMessage()
    ], "nothing says why a strategy left the list"


async def test_another_user_reads_a_public_strategy(
    pg_session_factory: Factory, api: _Api
) -> None:
    author = await _new_user(pg_session_factory)
    public = await _strategy(pg_session_factory, author)

    response = await api.get(f"{LIST}/{public}", OTHER_HEADERS)

    assert response.status_code == 200
    assert response.json()["id"] == str(public)


# --- statement counts -----------------------------------------------------------------


@contextmanager
def _captured_sql(engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record_statement(conn: object, cursor: object, statement: str, *rest: object) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record_statement)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _record_statement)


async def _trading_strategy(factory: Factory) -> UUID:
    """A public strategy with a closed trade, its author and one subscriber."""
    author = await _new_user(factory)
    subscriber = await _new_user(factory)
    strategy_id = await _strategy(factory, author)
    await _subscribe(factory, author, strategy_id, share="10", total="1000")
    await _subscribe(factory, subscriber, strategy_id, share="50", total="400")
    await _signal(factory, strategy_id, position_size="1", price="100", at=T0)
    await _signal(factory, strategy_id, position_size="0", price="110", at=T0 + timedelta(hours=1))
    return strategy_id


async def _sql_of(api: _Api, engine: AsyncEngine, path: str) -> list[str]:
    # The sign-in's own statements are not the read's: the stranger's row exists first.
    await api.get(path, OTHER_HEADERS)
    with _captured_sql(engine) as statements:
        response = await api.get(path, OTHER_HEADERS)
    assert response.status_code == 200, response.text
    return list(statements)


async def test_the_statement_count_is_the_same_for_one_strategy_and_for_twenty(
    pg_session_factory: Factory, pg_engine: AsyncEngine, api: _Api
) -> None:
    first = await _trading_strategy(pg_session_factory)
    one = await _sql_of(api, pg_engine, LIST)
    page = await _sql_of(api, pg_engine, f"{LIST}/{first}")

    for _ in range(19):
        await _trading_strategy(pg_session_factory)
    twenty = await _sql_of(api, pg_engine, LIST)

    assert len(await api.listed()) == 20
    assert len(twenty) == len(one), "the number of statements grew with the number of strategies"
    assert len(page) == len(one)


async def test_the_read_runs_in_one_read_only_snapshot_and_touches_no_ledger_or_payload(
    pg_session_factory: Factory, pg_engine: AsyncEngine, api: _Api
) -> None:
    await _trading_strategy(pg_session_factory)

    statements = await _sql_of(api, pg_engine, LIST)

    transaction = [each for each in statements if "SET TRANSACTION" in each]
    assert transaction == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"]
    read = statements[statements.index(transaction[0]) :]
    assert len(read) == 4, "the snapshot, the listings, the signals and the seats"
    assert not [each for each in statements if "ledger_entries" in each]
    assert not [each for each in statements if "raw_payload" in each]


def test_the_public_read_imports_nothing_of_the_ledger() -> None:
    """A public figure comes from signals. The port, the use case and the source
    name no ledger module, so no fill can reach a public body."""
    root = Path(strategy_manager.__file__).parent / "performance"
    for module in (
        root / "application" / "ports.py",
        root / "application" / "read_public_strategies.py",
        root / "infrastructure" / "public_strategies_source.py",
    ):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = [
            node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        ]
        assert imported, module
        assert not [name for name in imported if name and ".ledger" in name], module

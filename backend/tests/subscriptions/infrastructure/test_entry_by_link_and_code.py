"""Entering a strategy off the public list by its link or by an invitation code
(multi-user decision 41; tasks.md K.4) [DB].

A LINK strategy opens to whoever brings its current token, a PRIVATE one to whoever
brings a live code made for it, and a live code opens a LINK strategy too. That holds
for the public page, its record, the share preview and subscribing. The link or the
code is consulted only when the strategy does not open without it.

A wrong code answers what an unknown strategy answers. A code that was made for the
strategy and is dead says why (expired, revoked or spent), naming nobody. A wrong,
malformed or dead code counts as a failure of its user, and a user with
``MAX_FAILED_ATTEMPTS`` failures in the last hour has every further code refused
unread. A code is spent only by subscribing, in the seat's own transaction.

Each test goes through the application's routes over real PostgreSQL, ORM schema.
"""

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.strategies.domain.invite_code import MAX_FAILED_ATTEMPTS
from strategy_manager.strategies.infrastructure.code_entry_http import (
    CHECK_POOL_SIZE,
    check_engine_for,
)
from tests.identity_auth import ADMIN_HEADERS, OTHER_HEADERS, seed_admin, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.owner import seed_pool
from tests.strategies.infrastructure.test_strategy_authoring_scope import _seed_other

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
MARKET = ("bybit", "usdt-m", "USDT")
LOGGER = "strategy_manager.strategies.application.code_entry"
PAGE = "/api/public/strategies/{id}"
RECORD = "/api/public/strategies/{id}/record"
PREVIEW = "/api/strategies/{id}/share-preview"
SUBSCRIBE = "/api/subscriptions"
LOOKUP = "/api/public/invite-codes/lookup"
#: The code as its author was shown it, and as a reader may type it.
CODE = "K7QM-2XRA"
TYPED = " k7qm 2xra "
UNKNOWN_CODE = "B4TN-9WZE"
TOKEN = "t" * 43
OTHER_TOKEN = "u" * 43
WAIT_SECONDS = 10.0


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").encode()).hexdigest()


@dataclass(frozen=True)
class World:
    api: AsyncClient
    factory: Factory
    author: UUID
    reader: UUID
    reader_pool: int


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture
async def world(pg_session_factory: Factory) -> AsyncIterator[World]:  # noqa: F811
    """The admin authors, with a name; the other user reads, with a pool on the
    strategies' market and no failed attempt."""
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE invite_code_attempts"))
        await session.execute(text("UPDATE users SET display_name = NULL"))
        author = await seed_admin(session)
        reader = await _seed_other(session)
        await session.execute(
            text("UPDATE users SET display_name = 'The author' WHERE id = :id"), {"id": author}
        )
        await seed_pool(session, MARKET, user_id=author)
        reader_pool = await seed_pool(session, MARKET, user_id=reader)
        await session.commit()

    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield World(api, pg_session_factory, author, reader, int(reader_pool))
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE invite_code_attempts"))
        await session.commit()


async def _sql(world: World, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async with world.factory() as session:
        result = await session.execute(text(sql), params or {})
        rows = list(result) if result.returns_rows else []
        await session.commit()
    return rows


async def _strategy(world: World, visibility: str, token: str | None = None) -> UUID:
    strategy_id = uuid4()
    await seed_strategy(world.factory, strategy_id=strategy_id, author_id=world.author)
    await _sql(
        world,
        "UPDATE strategies SET visibility = :v, share_token = :t WHERE id = :id",
        {"v": visibility, "t": token, "id": strategy_id},
    )
    return strategy_id


async def _code(
    world: World,
    strategy_id: UUID,
    code: str = CODE,
    *,
    age: timedelta = timedelta(0),
    revoked: bool = False,
) -> UUID:
    code_id = uuid4()
    made = datetime.now(UTC) - age
    await _sql(
        world,
        "INSERT INTO invite_codes (id, strategy_id, code_hash, hint, created_at, expires_at, "
        "revoked_at) VALUES (:id, :s, :h, :hint, :c, :e, :r)",
        {
            "id": code_id,
            "s": strategy_id,
            "h": _hash(code),
            "hint": code[-4:],
            "c": made,
            "e": made + timedelta(days=7),
            "r": made if revoked else None,
        },
    )
    return code_id


async def _spend_as_the_author(world: World, code_id: UUID, strategy_id: UUID) -> None:
    """Marks ``code_id`` spent by the author's own seat."""
    seat = uuid4()
    await _sql(
        world,
        "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
        "SELECT :id, :u, :s, p.id, 10 FROM capital_pools p WHERE p.user_id = :u",
        {"id": seat, "u": world.author, "s": strategy_id},
    )
    await _sql(
        world,
        "UPDATE invite_codes SET redeemed_by = :u, redeemed_at = now(), subscription_id = :seat "
        "WHERE id = :id",
        {"u": world.author, "seat": seat, "id": code_id},
    )


async def _code_row(world: World, code_id: UUID) -> tuple[Any, ...]:
    [row] = await _sql(
        world,
        "SELECT redeemed_by, redeemed_at, subscription_id, revoked_at FROM invite_codes "
        "WHERE id = :id",
        {"id": code_id},
    )
    return tuple(row)


async def _failures(world: World, user: UUID) -> int:
    [(count,)] = await _sql(
        world, "SELECT count(*) FROM invite_code_attempts WHERE user_id = :u", {"u": user}
    )
    return int(count)


async def _fail_earlier(world: World, user: UUID, count: int, age: timedelta) -> None:
    for _ in range(count):
        await _sql(
            world,
            "INSERT INTO invite_code_attempts (user_id, attempted_at) VALUES (:u, :at)",
            {"u": user, "at": datetime.now(UTC) - age},
        )


async def _seats(world: World, strategy_id: UUID) -> list[Any]:
    return await _sql(
        world,
        "SELECT id FROM subscriptions WHERE user_id = :u AND strategy_id = :s",
        {"u": world.reader, "s": strategy_id},
    )


async def _read(
    world: World, route: str, strategy_id: UUID, **params: str
) -> Response:
    return await world.api.get(
        route.format(id=strategy_id), params=params, headers=OTHER_HEADERS
    )


async def _subscribe(world: World, strategy_id: UUID, **entry: str) -> Response:
    body = {"strategy_id": str(strategy_id), "allocation_percent": "10", **entry}
    return await world.api.post(SUBSCRIBE, json=body, headers=OTHER_HEADERS)


# --- the link ---------------------------------------------------------------------


@pytest.mark.parametrize("route", [PAGE, RECORD, PREVIEW])
async def test_a_link_strategy_opens_to_its_current_link_only(world: World, route: str) -> None:
    strategy_id = await _strategy(world, "LINK", TOKEN)
    await _strategy(world, "LINK", OTHER_TOKEN)
    unknown = await _read(world, route, uuid4())

    opened = await _read(world, route, strategy_id, link=TOKEN)
    refused = [
        await _read(world, route, strategy_id),
        await _read(world, route, strategy_id, link=OTHER_TOKEN),
        await _read(world, route, strategy_id, link=TOKEN[:-1] + "x"),
    ]

    assert opened.status_code == 200, opened.text
    assert [(each.status_code, each.json()) for each in refused] == [
        (404, unknown.json())
    ] * 3
    assert await _failures(world, world.reader) == 0


async def test_a_link_opens_nothing_but_a_link_strategy(world: World) -> None:
    await _strategy(world, "LINK", TOKEN)
    private = await _strategy(world, "PRIVATE")

    response = await _read(world, PAGE, private, link=TOKEN)

    assert response.status_code == 404


async def test_a_link_lets_its_holder_subscribe_and_nobody_else(world: World) -> None:
    strategy_id = await _strategy(world, "LINK", TOKEN)

    without = await _subscribe(world, strategy_id)
    wrong = await _subscribe(world, strategy_id, link_token=OTHER_TOKEN)
    assert [without.status_code, wrong.status_code] == [404, 404]
    assert await _seats(world, strategy_id) == []

    response = await _subscribe(world, strategy_id, link_token=TOKEN)

    assert response.status_code == 201, response.text
    seats = [tuple(row) for row in await _seats(world, strategy_id)]
    assert seats == [(UUID(response.json()["id"]),)]


# --- a live code ------------------------------------------------------------------


@pytest.mark.parametrize("visibility", ["PRIVATE", "LINK"])
@pytest.mark.parametrize("route", [PAGE, RECORD, PREVIEW])
async def test_a_live_code_opens_a_strategy_off_the_list_and_reading_spends_nothing(
    world: World, route: str, visibility: str
) -> None:
    strategy_id = await _strategy(world, visibility, TOKEN if visibility == "LINK" else None)
    code_id = await _code(world, strategy_id)

    response = await _read(world, route, strategy_id, code=TYPED)

    assert response.status_code == 200, response.text
    assert await _code_row(world, code_id) == (None, None, None, None)
    assert await _failures(world, world.reader) == 0


async def test_a_code_lets_its_holder_subscribe_once_and_is_spent_with_the_seat(
    world: World,
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)
    before = datetime.now(UTC)

    response = await _subscribe(world, strategy_id, invite_code=TYPED)

    assert response.status_code == 201, response.text
    seat = UUID(response.json()["id"])
    redeemed_by, redeemed_at, subscription_id, revoked_at = await _code_row(world, code_id)
    assert (redeemed_by, subscription_id, revoked_at) == (world.reader, seat, None)
    assert before <= redeemed_at <= datetime.now(UTC)
    listed = await world.api.get(
        f"/api/strategies/{strategy_id}/invite-codes", headers=ADMIN_HEADERS
    )
    assert listed.json() == []


# --- a code that opens nothing ----------------------------------------------------


@pytest.mark.parametrize("typed", [UNKNOWN_CODE, "not a code", "elsewhere"])
@pytest.mark.parametrize("route", [PAGE, RECORD, PREVIEW])
async def test_a_wrong_code_answers_as_no_strategy_and_counts_against_its_user(
    world: World,
    route: str,
    typed: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    elsewhere = await _strategy(world, "PRIVATE")
    await _code(world, elsewhere)
    unknown = await _read(world, route, uuid4())

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = await _read(
            world, route, strategy_id, code=CODE if typed == "elsewhere" else typed
        )

    assert (response.status_code, response.json()) == (404, unknown.json())
    assert await _failures(world, world.reader) == 1
    said = [each for each in caplog.records if each.name == LOGGER]
    assert [each.levelno for each in said] == [logging.WARNING]
    line = said[0].getMessage()
    assert str(world.reader) in line and str(strategy_id) in line
    assert "K7QM" not in line and "2XRA" not in line and "B4TN" not in line


async def test_a_wrong_code_subscribes_nobody_and_counts(world: World) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    await _code(world, strategy_id)

    response = await _subscribe(world, strategy_id, invite_code=UNKNOWN_CODE)

    assert response.status_code == 404
    assert response.json()["detail"] == f"no strategy registered under id {strategy_id}"
    assert await _seats(world, strategy_id) == []
    assert await _failures(world, world.reader) == 1


@pytest.mark.parametrize("reason", ["EXPIRED", "REVOKED", "SPENT"])
@pytest.mark.parametrize("route", [PAGE, RECORD, PREVIEW, SUBSCRIBE])
async def test_a_dead_code_says_why_naming_nobody_and_counts(
    world: World, route: str, reason: str
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(
        world,
        strategy_id,
        age=timedelta(days=8) if reason == "EXPIRED" else timedelta(0),
        revoked=reason == "REVOKED",
    )
    if reason == "SPENT":
        await _spend_as_the_author(world, code_id, strategy_id)
    before = await _code_row(world, code_id)

    if route == SUBSCRIBE:
        response = await _subscribe(world, strategy_id, invite_code=CODE)
    else:
        response = await _read(world, route, strategy_id, code=CODE)

    assert response.status_code == 410, response.text
    detail = response.json()["detail"]
    assert (detail["error"], detail["reason"]) == ("INVITE_CODE_NOT_LIVE", reason)
    assert str(world.author) not in response.text and "The author" not in response.text
    assert await _code_row(world, code_id) == before
    assert await _seats(world, strategy_id) == []
    assert await _failures(world, world.reader) == 1


# --- consulted only when needed ---------------------------------------------------


@pytest.mark.parametrize(
    ("visibility", "link"), [("PUBLIC", None), ("LINK", TOKEN)], ids=["public", "link"]
)
async def test_a_code_is_never_read_when_the_strategy_opens_without_it(
    world: World, visibility: str, link: str | None
) -> None:
    strategy_id = await _strategy(world, visibility, TOKEN if visibility == "LINK" else None)
    code_id = await _code(world, strategy_id)
    entry = {} if link is None else {"link": link}

    read = await _read(world, PAGE, strategy_id, code=UNKNOWN_CODE, **entry)
    subscribed = await _subscribe(
        world,
        strategy_id,
        invite_code=CODE,
        **({} if link is None else {"link_token": link}),
    )

    assert read.status_code == 200, read.text
    assert subscribed.status_code == 201, subscribed.text
    assert await _code_row(world, code_id) == (None, None, None, None)
    assert await _failures(world, world.reader) == 0


async def test_a_refused_subscription_spends_no_code(world: World) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)
    await _sql(world, "DELETE FROM capital_pools WHERE id = :id", {"id": world.reader_pool})

    response = await _subscribe(world, strategy_id, invite_code=CODE)

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "NO_POOL_FOR_MARKET"
    assert await _code_row(world, code_id) == (None, None, None, None)
    assert await _failures(world, world.reader) == 0


# --- the limit ----------------------------------------------------------------------


async def test_the_tenth_failure_is_answered_and_then_every_code_is_refused_unread(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)
    await _fail_earlier(world, world.reader, MAX_FAILED_ATTEMPTS - 1, timedelta(minutes=59))

    tenth = await _read(world, PAGE, strategy_id, code=UNKNOWN_CODE)
    assert tenth.status_code == 404
    assert await _failures(world, world.reader) == MAX_FAILED_ATTEMPTS
    caplog.clear()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        answers = [
            await _read(world, PAGE, strategy_id, code=CODE),
            await _read(world, PREVIEW, strategy_id, code=CODE),
            await _subscribe(world, strategy_id, invite_code=CODE),
        ]

    assert [each.status_code for each in answers] == [429, 429, 429]
    assert {each.json()["detail"]["error"] for each in answers} == {"TOO_MANY_CODE_ATTEMPTS"}
    assert await _failures(world, world.reader) == MAX_FAILED_ATTEMPTS
    assert await _code_row(world, code_id) == (None, None, None, None)
    assert await _seats(world, strategy_id) == []
    said = [each for each in caplog.records if each.name == LOGGER]
    assert [each.levelno for each in said] == [logging.WARNING] * 3
    assert all(str(world.reader) in each.getMessage() for each in said)


async def test_failures_older_than_the_hour_or_of_another_user_do_not_count(
    world: World,
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    await _code(world, strategy_id)
    await _fail_earlier(world, world.reader, MAX_FAILED_ATTEMPTS, timedelta(minutes=61))
    await _fail_earlier(world, world.author, MAX_FAILED_ATTEMPTS, timedelta(0))

    response = await _read(world, PAGE, strategy_id, code=CODE)

    assert response.status_code == 200, response.text


async def test_a_failure_prunes_its_users_failures_older_than_the_hour(world: World) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    await _fail_earlier(world, world.reader, 3, timedelta(minutes=61))
    await _fail_earlier(world, world.author, 3, timedelta(minutes=61))

    await _read(world, PAGE, strategy_id, code=UNKNOWN_CODE)

    assert await _failures(world, world.reader) == 1
    assert await _failures(world, world.author) == 3


# --- one at a time ------------------------------------------------------------------


async def _not_done_while_held(task: "asyncio.Task[Response]") -> None:
    await asyncio.sleep(0.5)
    assert not task.done()


async def test_one_users_codes_are_checked_one_at_a_time(world: World) -> None:
    """Two checks of one user never both read the count before either writes."""
    strategy_id = await _strategy(world, "PRIVATE")
    async with world.factory() as holder:
        await holder.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtext('invite-code-attempts'), "
                "hashtext(:user))"
            ),
            {"user": str(world.reader)},
        )
        task = asyncio.create_task(_read(world, PAGE, strategy_id, code=UNKNOWN_CODE))
        await _not_done_while_held(task)
        await holder.commit()

    assert (await task).status_code == 404
    assert await _failures(world, world.reader) == 1


async def _ask_with_code(api: AsyncClient, route: str, strategy_id: UUID) -> Response:
    if route == SUBSCRIBE:
        body = {"strategy_id": str(strategy_id), "allocation_percent": "10"}
        return await api.post(
            SUBSCRIBE, json={**body, "invite_code": UNKNOWN_CODE}, headers=OTHER_HEADERS
        )
    if route == LOOKUP:
        return await api.post(LOOKUP, json={"code": UNKNOWN_CODE}, headers=OTHER_HEADERS)
    return await api.get(
        route.format(id=strategy_id), params={"code": UNKNOWN_CODE}, headers=OTHER_HEADERS
    )


@pytest.mark.parametrize("route", [PAGE, RECORD, PREVIEW, SUBSCRIBE, LOOKUP])
async def test_checks_beside_requests_that_hold_every_pooled_connection_still_answer(
    world: World, pg_engine: AsyncEngine, route: str  # noqa: F811
) -> None:
    """Each request holds its own connection while its code is checked. Drawn from the
    same pool, as many checks as connections held every one and waited for a second
    until the pool timed out: a 500 for each, and a stall for every request beside them,
    the webhook's included."""
    strategy_id = await _strategy(world, "PRIVATE")
    tight = create_async_engine(pg_engine.url, pool_size=2, max_overflow=0, pool_timeout=2)
    tight_factory = async_sessionmaker(tight, class_=AsyncSession, expire_on_commit=False)
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with tight_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as api:
            answers = await asyncio.gather(
                *(_ask_with_code(api, route, strategy_id) for _ in range(2))
            )
    finally:
        await tight.dispose()

    assert [answer.status_code for answer in answers] == [404, 404]
    assert await _failures(world, world.reader) == 2


async def _waiting_on_an_advisory_lock(world: World) -> int:
    rows = await _sql(
        world,
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
        "AND wait_event_type = 'Lock' AND wait_event = 'advisory'",
    )
    return int(rows[0][0])


async def test_concurrent_checks_never_hold_more_connections_than_their_own_pool(
    world: World,
) -> None:
    """A lookup holds no connection of its request while its code is checked, so a
    check with no pool of its own opened one connection per concurrent lookup, each held
    while it waited on the user's lock: enough of them would use up the server's
    connections, the worker's and the webhook's included."""
    beyond = CHECK_POOL_SIZE + 3
    async with world.factory() as holder:
        await holder.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtext('invite-code-attempts'), "
                "hashtext(:user))"
            ),
            {"user": str(world.reader)},
        )
        tasks = [asyncio.create_task(_lookup(world, UNKNOWN_CODE)) for _ in range(beyond)]
        deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
        while await _waiting_on_an_advisory_lock(world) < CHECK_POOL_SIZE:
            assert asyncio.get_running_loop().time() < deadline, "no check reached the lock"
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.5)
        waiting = await _waiting_on_an_advisory_lock(world)
        await holder.commit()

    answers = await asyncio.gather(*tasks)
    assert waiting == CHECK_POOL_SIZE
    assert [answer.status_code for answer in answers] == [404] * beyond
    assert await _failures(world, world.reader) == beyond


async def test_the_checks_pool_belongs_to_its_request_engine_and_closes_with_it(
    pg_engine: AsyncEngine,  # noqa: F811
) -> None:
    """Built once per request engine and closed with it: a test's engine is disposed at
    its end, and a pool outliving it would keep connections of a finished event loop."""
    request_engine = create_async_engine(pg_engine.url)
    async with AsyncSession(request_engine) as request_session:
        check_engine = check_engine_for(request_session)
        assert check_engine_for(request_session) is check_engine
        async with AsyncSession(check_engine) as checking:
            await checking.execute(text("SELECT 1"))
            await checking.commit()
        assert check_engine.sync_engine.pool.checkedin() == 1  # type: ignore[attr-defined]

    await request_engine.dispose()

    assert check_engine.sync_engine.pool.checkedin() == 0  # type: ignore[attr-defined]


async def test_a_code_spent_while_a_subscription_waits_on_it_is_refused(world: World) -> None:
    """The spend waits on the code's row and reads it again, so one code makes one seat."""
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)
    async with world.factory() as holder:
        await holder.execute(
            text("SELECT id FROM invite_codes WHERE id = :id FOR UPDATE"), {"id": code_id}
        )
        task = asyncio.create_task(_subscribe(world, strategy_id, invite_code=CODE))
        await _not_done_while_held(task)
        seat = uuid4()
        await holder.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, "
                "allocation_percent) SELECT :id, :u, :s, p.id, 10 FROM capital_pools p "
                "WHERE p.user_id = :u"
            ),
            {"id": seat, "u": world.author, "s": strategy_id},
        )
        await holder.execute(
            text(
                "UPDATE invite_codes SET redeemed_by = :u, redeemed_at = now(), "
                "subscription_id = :seat WHERE id = :id"
            ),
            {"u": world.author, "seat": seat, "id": code_id},
        )
        await holder.commit()

    response = await task
    assert response.status_code == 410, response.text
    assert response.json()["detail"]["reason"] == "SPENT"
    assert await _seats(world, strategy_id) == []
    assert (await _code_row(world, code_id))[2] == seat


# --- what nothing opens -----------------------------------------------------------


@pytest.mark.parametrize("route", [PAGE, RECORD, PREVIEW, SUBSCRIBE])
async def test_a_live_code_opens_nothing_of_an_author_with_no_name(
    world: World, route: str
) -> None:
    """A page names its author (decision 27), so a code opens none without a name."""
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)
    await _sql(world, "UPDATE users SET display_name = NULL WHERE id = :id", {"id": world.author})

    if route == SUBSCRIBE:
        response = await _subscribe(world, strategy_id, invite_code=CODE)
    else:
        response = await _read(world, route, strategy_id, code=CODE)

    assert response.status_code == 404, response.text
    assert await _code_row(world, code_id) == (None, None, None, None)
    assert await _seats(world, strategy_id) == []


@pytest.mark.parametrize("field", ["link", "code"])
async def test_a_link_or_code_longer_than_any_is_refused_unread(world: World, field: str) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    long = "A" * 65

    read = await _read(world, PAGE, strategy_id, **{field: long})
    subscribed = await _subscribe(
        world, strategy_id, **{"link_token" if field == "link" else "invite_code": long}
    )

    assert [read.status_code, subscribed.status_code] == [422, 422]
    assert long not in read.text and long not in subscribed.text
    assert await _failures(world, world.reader) == 0


# --- finding a strategy by its code alone (tasks.md K.6) ----------------------------



async def _lookup(world: World, code: str) -> Response:
    return await world.api.post(LOOKUP, json={"code": code}, headers=OTHER_HEADERS)


@pytest.mark.parametrize("visibility", ["PRIVATE", "LINK"])
async def test_a_live_code_alone_names_its_strategy_and_spends_nothing(
    world: World, visibility: str
) -> None:
    """Explore's "I have a code" has no strategy id: the code names the strategy whose
    page it then opens. Typed loosely, as a reader may."""
    strategy_id = await _strategy(world, visibility, TOKEN if visibility == "LINK" else None)
    await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)

    response = await _lookup(world, TYPED)

    assert (response.status_code, response.json()) == (200, {"strategy_id": str(strategy_id)})
    assert await _code_row(world, code_id) == (None, None, None, None)
    assert await _failures(world, world.reader) == 0


@pytest.mark.parametrize("typed", [UNKNOWN_CODE, "not a code"])
async def test_a_code_that_names_no_strategy_answers_404_and_counts(
    world: World, typed: str, caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    await _code(world, strategy_id)

    with caplog.at_level(logging.INFO, logger=LOGGER):
        response = await _lookup(world, typed)

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "no strategy opens to that code"}
    assert await _failures(world, world.reader) == 1
    said = [each for each in caplog.records if each.name == LOGGER]
    assert [each.levelno for each in said] == [logging.WARNING]
    line = said[0].getMessage()
    assert str(world.reader) in line
    assert "K7QM" not in line and "B4TN" not in line and str(strategy_id) not in line


@pytest.mark.parametrize("reason", ["EXPIRED", "REVOKED", "SPENT"])
async def test_a_dead_code_alone_says_why_naming_nobody_and_counts(
    world: World, reason: str
) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(
        world,
        strategy_id,
        age=timedelta(days=8) if reason == "EXPIRED" else timedelta(0),
        revoked=reason == "REVOKED",
    )
    if reason == "SPENT":
        await _spend_as_the_author(world, code_id, strategy_id)

    response = await _lookup(world, CODE)

    assert response.status_code == 410, response.text
    detail = response.json()["detail"]
    assert (detail["error"], detail["reason"]) == ("INVITE_CODE_NOT_LIVE", reason)
    assert str(strategy_id) not in response.text and str(world.author) not in response.text
    assert await _failures(world, world.reader) == 1


async def test_a_lookup_past_the_limit_is_refused_unread(world: World) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    code_id = await _code(world, strategy_id)
    await _fail_earlier(world, world.reader, MAX_FAILED_ATTEMPTS, timedelta(minutes=30))

    response = await _lookup(world, CODE)

    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "TOO_MANY_CODE_ATTEMPTS"
    assert str(strategy_id) not in response.text
    assert await _failures(world, world.reader) == MAX_FAILED_ATTEMPTS
    assert await _code_row(world, code_id) == (None, None, None, None)


async def test_lookup_failures_and_page_failures_share_one_limit(world: World) -> None:
    strategy_id = await _strategy(world, "PRIVATE")
    await _code(world, strategy_id)
    await _fail_earlier(world, world.reader, MAX_FAILED_ATTEMPTS - 1, timedelta(minutes=30))

    last = await _lookup(world, UNKNOWN_CODE)
    page = await _read(world, PAGE, strategy_id, code=CODE)

    assert [last.status_code, page.status_code] == [404, 429]


async def test_a_lookup_code_longer_than_any_is_refused_unread(world: World) -> None:
    long = "A" * 33

    response = await _lookup(world, long)

    assert response.status_code == 422
    assert long not in response.text
    assert await _failures(world, world.reader) == 0

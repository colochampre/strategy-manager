"""The cross-user sweep (multi-user design AD8 and D.1; tasks.md G.5).

"Each endpoint gets one cross-user test: user B requests user A's resource by id
and receives 404, and no row changes. This is the check that catches a missing
filter. The gate cannot." So the route list comes from the app, not from memory:
a route added later with no probe fails the first test below.

One world, on real PostgreSQL, through the real ``current_user``. A is the admin
and holds everything; B signs in as somebody else and holds a pool on one of A's
markets and a seat on A's public strategy, so B stands as close to A's rows as a
user can, and a filter that stopped at "does B hold this strategy" is caught.

A probe is one of two kinds:

* it names a thing of A's and answers 404. No row of any table moves, and A asking
  the very same thing is not told 404, so the 404 is not a typo in the probe. The
  answer is the one an id nobody holds gets: the 404 says nothing of A;
* it asks for B's own (a collection, or a write about B) and answers its status.
  Nothing of A's shows in the answer and no row of A's moves.

The admin-only routes are out: each answers 403 to B, proven request by request in
``test_every_api_route_is_guarded.py``.
"""

import base64
import hashlib
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.save_credential import SaveCredential
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.credentials_router import get_save_credential
from strategy_manager.execution.infrastructure.live_exposure import SqlAlchemyLiveExposure
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.accounts.fakes import (
    BYBIT_KEY,
    BYBIT_SECRET,
    TRANSFER_SNAPSHOT,
    RecordingInspector,
    TickingClock,
    registry_for,
)
from tests.identity.infrastructure.test_every_api_route_is_guarded import _admin_only, _routes
from tests.identity_auth import (
    ADMIN_EMAIL,
    ADMIN_HEADERS,
    OTHER_EMAIL,
    OTHER_HEADERS,
    seed_admin,
    sign_in_as_admin,
)
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import ensure_author_subscription, ensure_pool, seed_snapshot, seed_trade_key
from tests.performance.infrastructure.test_allocation_fills_source import (
    _fill,
    _record,
    _seed_allocation,
)
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

#: A and B each hold a pool here, so B's own answers come from A's very market.
SHARED_MARKET = ("bybit", "usdt-m", "USDT")
#: Only A holds a pool here.
MARKET_OF_A = ("binance", "usdt-m", "USDT")
#: Text that appears nowhere unless a row of A's reached the answer. Upper case
#: and a dotted figure, so no uuid or timestamp can spell one by chance.
KEY_HINT_OF_A = "QZXW"
CLOSED_PAIR_OF_A = "SOLUSDT"
OPEN_PAIR_OF_A = "STXUSDT"
BALANCE_OF_A = "7654.32"
#: The last four of A's invitation code, in Crockford's upper case.
CODE_HINT_OF_A = "VRXT"
#: A's code as its author was shown it. Whoever holds it may learn which strategy it
#: opens (tasks.md K.6), and nothing else of A's.
PLAIN_CODE_OF_A = "K7QM-VRXT"

PRIVATE = "the private strategy of A"
PUBLIC = "the public strategy of A, where B holds a seat"
CLOSED_TRADE = "a closed trade of A, on the public strategy"
SEAT_OF_A = "the seat of A on the public strategy"
ORDER_OF_A = "an order of A still in flight"
CODE_OF_A = "a live invitation code of A, on the private strategy"


class _Catalog:
    async def available_pairs(self, pool: tuple[str, str, str]) -> frozenset[str]:
        return frozenset({"ETHUSDT"})


@dataclass(frozen=True)
class Probe:
    method: str
    path: str
    #: Path parameter -> a name above, or the literal value.
    at: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, Any] | None = None
    answers: int = 404
    #: Where A's own request is not a 404, when that is not ``at``.
    served_at: Mapping[str, str] | None = None
    #: The ids swapped for one nobody holds, for the 404 to compare with.
    unknown: tuple[str, ...] = (PRIVATE, PUBLIC, CLOSED_TRADE, SEAT_OF_A)
    #: A trace of A's, or the name of an id of A's, this route shows on purpose.
    shows: tuple[str, ...] = ()


def _market(market: tuple[str, str, str], currency: str) -> dict[str, str]:
    return {"exchange": market[0], "venue": market[1], currency: market[2]}


_STRATEGY = "/api/strategies/{strategy_id}"
_PERFORMANCE = "/api/performance/strategies/{strategy_id}"
_SUBSCRIPTION = "/api/subscriptions/{subscription_id}"
_POOL_PERFORMANCE = "/api/performance/pools/{exchange}/{venue}/{ccy}"
_PAIRS = "/api/pools/{exchange}/{venue}/{settlement_currency}/available-pairs"
_ON_PUBLIC = {"strategy_id": PUBLIC}
_ON_PRIVATE = {"strategy_id": PRIVATE}
_ON_SEAT = {"subscription_id": SEAT_OF_A}
_NEW_STRATEGY = {
    "id": str(uuid4()),
    "name": "a strategy of B",
    "exchange": SHARED_MARKET[0],
    "venue": SHARED_MARKET[1],
    "settlement_currency": SHARED_MARKET[2],
    "fill_mode": "PARTIAL",
    "allocation_percent": "100",
    "allowed_pairs": ["ETHUSDT"],
}

PROBES: tuple[Probe, ...] = (
    # The author's routes: A's public strategy is on every page, and still not B's
    # to read here or to change.
    Probe("GET", _STRATEGY, _ON_PUBLIC),
    Probe("PATCH", _STRATEGY, _ON_PUBLIC, {"name": "taken over"}),
    Probe("DELETE", _STRATEGY, _ON_PUBLIC),
    Probe("GET", f"{_STRATEGY}/events", _ON_PUBLIC),
    Probe("POST", f"{_STRATEGY}/archive", _ON_PUBLIC),
    Probe("POST", f"{_STRATEGY}/webhook-secret", _ON_PUBLIC),
    Probe("PUT", f"{_STRATEGY}/allowed-pairs", _ON_PUBLIC, {"pairs": ["ETHUSDT"]}),
    # A's invitation codes (decision 41): none made, listed or revoked by B.
    Probe("POST", f"{_STRATEGY}/invite-codes", _ON_PRIVATE),
    Probe("GET", f"{_STRATEGY}/invite-codes", _ON_PRIVATE),
    Probe(
        "DELETE",
        f"{_STRATEGY}/invite-codes/{{code_id}}",
        {"strategy_id": PRIVATE, "code_id": CODE_OF_A},
        unknown=(PRIVATE, CODE_OF_A),
    ),
    # What a stranger may see of a public strategy, asked of a private one.
    Probe("GET", f"{_STRATEGY}/share-preview", _ON_PRIVATE),
    # A private strategy has no public page for its own author either, nor for B, who
    # holds no seat on it (a live seat would open it: tasks.md J.1).
    Probe("GET", "/api/public/strategies/{strategy_id}", _ON_PRIVATE, served_at=_ON_PUBLIC),
    # Nor a record (I.12a): the author's real trades are drawn only for a public strategy.
    Probe("GET", "/api/public/strategies/{strategy_id}/record", _ON_PRIVATE, served_at=_ON_PUBLIC),
    Probe("POST", "/api/subscriptions", body={"strategy_id": PRIVATE, "allocation_percent": "30"}),
    # Holding A's code, B learns which strategy it opens, on purpose; nothing is spent.
    Probe(
        "POST",
        "/api/public/invite-codes/lookup",
        body={"code": PLAIN_CODE_OF_A},
        answers=200,
        shows=(PRIVATE,),
    ),
    # A's own figures: none on a strategy B never held, none of A's where B holds a seat.
    Probe("GET", _PERFORMANCE, _ON_PRIVATE),
    Probe("GET", _PERFORMANCE, _ON_PUBLIC, answers=200),
    Probe("GET", f"{_PERFORMANCE}/trades", _ON_PRIVATE),
    Probe("GET", f"{_PERFORMANCE}/trades", _ON_PUBLIC, answers=200),
    Probe(
        "GET",
        f"{_PERFORMANCE}/trades/{{allocation_id}}/fills",
        {"strategy_id": PUBLIC, "allocation_id": CLOSED_TRADE},
        unknown=(CLOSED_TRADE,),  # B holds the strategy, so only the trade is unknown.
    ),
    # A's seat, on a strategy where B holds one too.
    Probe("PATCH", _SUBSCRIPTION, _ON_SEAT, {"allocation_percent": "10"}),
    Probe("POST", f"{_SUBSCRIPTION}/leave", _ON_SEAT),
    # A market only A holds, and one both hold.
    Probe("GET", _POOL_PERFORMANCE, _market(MARKET_OF_A, "ccy")),
    Probe("GET", _POOL_PERFORMANCE, _market(SHARED_MARKET, "ccy"), answers=200),
    Probe("GET", _PAIRS, _market(MARKET_OF_A, "settlement_currency")),
    # A holds the key; B holds none to delete, and saving theirs leaves A's alone.
    Probe("DELETE", "/api/credentials/{exchange}", {"exchange": SHARED_MARKET[0]}),
    Probe(
        "PUT",
        "/api/credentials/{exchange}",
        {"exchange": SHARED_MARKET[0]},
        {"api_key": BYBIT_KEY, "api_secret": BYBIT_SECRET},
        answers=200,
    ),
    # The lists: each one B's alone.
    Probe("GET", "/api/credentials", answers=200),
    Probe("GET", "/api/pools", answers=200),
    Probe("GET", "/api/positions/open", answers=200),
    Probe("GET", "/api/strategies", answers=200),
    Probe("GET", "/api/subscriptions", answers=200),
    Probe("GET", "/api/subscriptions/held", answers=200),
    # Decision 30: the capital behind a public strategy is the one public figure.
    Probe("GET", "/api/public/strategies", answers=200, shows=(BALANCE_OF_A,)),
    # About B alone, or nobody.
    Probe("GET", "/api/me", answers=200),
    Probe("POST", "/api/me/mode", body={"mode": "SIMULATION"}, answers=200),
    Probe("PUT", "/api/me/display-name", body={"display_name": "Somebody"}, answers=200),
    Probe("POST", "/api/strategies", body=_NEW_STRATEGY, answers=201),
    Probe("GET", "/api/webhook-origin", answers=200),
)


@dataclass(frozen=True)
class World:
    api: AsyncClient
    factory: Factory
    a: UUID
    ids: dict[str, str]

    def traces_of_a(self, probe: Probe) -> tuple[str, ...]:
        """What no answer to B may carry. The public strategy's id is not one: its
        page is for everybody. Nor is an id the probe itself sent: an answer may
        repeat what B typed, and the 404's own test decides what that gives away."""
        sent = [*probe.at.values(), *(probe.body or {}).values()]
        secret = (PRIVATE, CLOSED_TRADE, SEAT_OF_A, ORDER_OF_A, CODE_OF_A)
        ids = (self.ids[name] for name in secret if name not in sent and name not in probe.shows)
        traces = (
            *ids,
            KEY_HINT_OF_A,
            CODE_HINT_OF_A,
            CLOSED_PAIR_OF_A,
            OPEN_PAIR_OF_A,
            BALANCE_OF_A,
            ADMIN_EMAIL,
        )
        return tuple(trace for trace in traces if trace not in probe.shows)


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)
    # Production's setting: a route that behaves otherwise under the brake is swept
    # as it runs, and ``/api/me/mode`` answers at all.
    monkeypatch.setattr(get_settings(), "dry_run", False)
    monkeypatch.setattr(
        get_settings(),
        "master_encryption_key",
        base64.b64encode(os.urandom(MASTER_KEY_BYTES)).decode(),
    )


async def _seed_b(session: AsyncSession) -> UUID:
    """The ``users`` row of the e-mail ``OTHER_HEADERS`` sign in as."""
    await session.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email) ON CONFLICT (email) DO NOTHING"),
        {"id": uuid4(), "email": OTHER_EMAIL},
    )
    found = (
        await session.execute(
            text("SELECT id FROM users WHERE email = :email"), {"email": OTHER_EMAIL}
        )
    ).scalar_one()
    return UUID(str(found))


async def _clear(session: AsyncSession) -> None:
    """What the fixtures' own truncates leave behind. Run on the way out as well:
    ``users`` outlives a test, and the next one expects nobody LIVE and nobody named."""
    await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
    await session.execute(text("TRUNCATE strategy_enablement_events"))
    await session.execute(text("UPDATE users SET display_name = NULL, mode = 'SIMULATION'"))


async def _seed_the_two_users(factory: Factory) -> tuple[UUID, UUID, int]:
    async with factory() as session:
        await _clear(session)
        a = await seed_admin(session)
        b = await _seed_b(session)
        # Both LIVE: B going back to simulation is a write, and a row of A's that
        # moved with it shows.
        await session.execute(
            text("UPDATE users SET mode = 'LIVE' WHERE id IN (:a, :b)"), {"a": a, "b": b}
        )
        await ensure_pool(session, SHARED_MARKET, user_id=a)
        await ensure_pool(session, MARKET_OF_A, user_id=a)
        b_pool = await ensure_pool(session, SHARED_MARKET, user_id=b)
        await seed_snapshot(
            session,
            SHARED_MARKET,
            total=Decimal(BALANCE_OF_A),
            available=Decimal(BALANCE_OF_A),
            observed_at=datetime.now(UTC),
            user_id=a,
        )
        await seed_trade_key(session, a)
        await session.execute(
            text("UPDATE exchange_credentials SET api_key_last4 = :hint WHERE user_id = :user"),
            {"hint": KEY_HINT_OF_A, "user": a},
        )
        await session.commit()
    return a, b, b_pool


async def _seed_the_rows_of_a(factory: Factory, a: UUID, b: UUID, b_pool: int) -> dict[str, str]:
    private = await seeds.strategy(factory, visibility="PRIVATE", author_id=a)
    public = await seeds.strategy(factory, visibility="PUBLIC", author_id=a)
    async with factory() as session:
        await ensure_author_subscription(session, private)
        seat = await ensure_author_subscription(session, public)
        await session.commit()
    await seeds.subscription(factory, b, public, b_pool)
    await seeds.open_allocation(factory, a, public, symbol=OPEN_PAIR_OF_A)
    _, closed, attempt = await _seed_allocation(factory, strategy_id=public, user_id=a)
    legs = (("BUY", "100"), ("SELL", "110"))
    await _record(
        factory,
        *(
            _fill(
                strategy_id=public, allocation_id=closed, attempt_id=attempt, side=side,
                quantity="1", price=price, symbol=CLOSED_PAIR_OF_A, user_id=a,
            )
            for side, price in legs
        ),
    )
    # An attempt with no order id yet is not in flight: the venue has never heard of it.
    async with factory() as session:
        await session.execute(
            text("UPDATE execution_attempts SET exchange_order_id = :order WHERE id = :id"),
            {"order": "1234567890123", "id": attempt},
        )
        code = uuid4()
        made = datetime.now(UTC)
        await session.execute(
            text(
                "INSERT INTO invite_codes (id, strategy_id, code_hash, hint, created_at, "
                "expires_at) VALUES (:id, :strategy, :hash, :hint, :made, :expires)"
            ),
            {
                "id": code,
                "strategy": private,
                "hash": hashlib.sha256(PLAIN_CODE_OF_A.replace("-", "").encode()).hexdigest(),
                "hint": CODE_HINT_OF_A,
                "made": made,
                "expires": made + timedelta(days=7),
            },
        )
        await session.commit()
    return {
        CODE_OF_A: str(code),
        PRIVATE: str(private),
        PUBLIC: str(public),
        CLOSED_TRADE: str(closed),
        SEAT_OF_A: str(seat),
        ORDER_OF_A: str(attempt),
    }


@pytest.fixture
async def world(pg_session_factory: Factory) -> AsyncIterator[World]:  # noqa: F811
    a, b, b_pool = await _seed_the_two_users(pg_session_factory)
    ids = await _seed_the_rows_of_a(pg_session_factory, a, b, b_pool)
    cipher = EnvelopeCipher(os.urandom(MASTER_KEY_BYTES))
    app = create_app()

    async def _session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    async def _save_over_the_real_vault(
        session: Annotated[AsyncSession, Depends(shared_db.get_session)],
    ) -> SaveCredential:
        clock = TickingClock()
        return SaveCredential(
            registry_for(RecordingInspector(TRANSFER_SNAPSHOT)),
            SqlAlchemyCredentialVault(session, cipher, clock),
            SqlAlchemyCapitalPoolWriter(session),
            session,
            clock,
            PoolLockAdapter(session),
            SqlAlchemyLiveExposure(session),
        )

    app.dependency_overrides[shared_db.get_session] = _session
    app.dependency_overrides[get_pair_catalog] = _Catalog
    app.dependency_overrides[get_save_credential] = _save_over_the_real_vault
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield World(api, pg_session_factory, a, ids)
    async with pg_session_factory() as session:
        await _clear(session)
        await session.commit()


async def _digest(session: AsyncSession, table: str, where: str, user: UUID | None) -> str:
    """A row count and an md5 of every row's text: an UPDATE shows as an INSERT does."""
    row = (
        await session.execute(
            text(
                f"SELECT count(*), md5(coalesce(string_agg(t::text, ',' "  # noqa: S608
                f"ORDER BY t::text), '')) FROM {table} t {where}"
            ),
            {} if user is None else {"user": user},
        )
    ).one()
    return f"{row[0]}:{row[1]}"


async def _every_row(factory: Factory) -> dict[str, str]:
    """Every table but ``users``: a request stamps the signed-in user's own row."""
    async with factory() as session:
        tables = (
            await session.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'users' ORDER BY tablename"
                )
            )
        ).scalars()
        return {table: await _digest(session, table, "", None) for table in list(tables)}


async def _rows_of(factory: Factory, user: UUID) -> dict[str, str]:
    """Every row that names ``user`` as its owner, and their ``users`` row."""
    async with factory() as session:
        owned = (
            await session.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name IN ('user_id', 'author_id') "
                    "ORDER BY table_name"
                )
            )
        ).all()
        rows = {
            table: await _digest(session, table, f"WHERE {column} = :user", user)
            for table, column in owned
        }
        rows["users"] = await _digest(session, "users", "WHERE id = :user", user)
    return rows


async def _send(
    world: World, probe: Probe, headers: dict[str, str], ids: dict[str, str] | None = None
) -> Response:
    known = world.ids if ids is None else ids
    values = {name: known.get(value, value) for name, value in probe.at.items()}
    body = (
        None
        if probe.body is None
        else {
            name: known.get(value, value) if isinstance(value, str) else value
            for name, value in probe.body.items()
        }
    )
    return await world.api.request(
        probe.method, probe.path.format(**values), json=body, headers=headers
    )


def _without(answer: str, ids: dict[str, str]) -> str:
    """The answer with every id swapped for its name, so two answers about two ids
    compare."""
    for name, value in ids.items():
        answer = answer.replace(value, name)
    return answer


def _name(probe: Probe) -> str:
    return f"{probe.method} {probe.path} {'/'.join(probe.at.values())}".strip()


def test_every_api_route_has_a_cross_user_probe() -> None:
    """The route list is the app's. A new route with no probe fails here, and so does
    a probe of a route the app no longer serves."""
    scoped = {key for key in _routes() if key[1].startswith("/api/")} - set(_admin_only())

    assert {(probe.method, probe.path) for probe in PROBES} == scoped
    assert len(scoped) >= 30  # a walk that found nothing would pass for free


@pytest.mark.parametrize("probe", PROBES, ids=_name)
async def test_b_reaches_nothing_of_a(probe: Probe, world: World) -> None:
    every_row = await _every_row(world.factory)
    rows_of_a = await _rows_of(world.factory, world.a)

    answer = await _send(world, probe, OTHER_HEADERS)

    assert answer.status_code == probe.answers, answer.text
    assert [trace for trace in world.traces_of_a(probe) if trace in answer.text] == []
    assert await _rows_of(world.factory, world.a) == rows_of_a
    if probe.answers != 404:
        return
    assert await _every_row(world.factory) == every_row
    nobody = {**world.ids, **{name: str(uuid4()) for name in probe.unknown}}
    unknown = await _send(world, probe, OTHER_HEADERS, nobody)
    assert (unknown.status_code, _without(unknown.text, nobody)) == (
        404,
        _without(answer.text, world.ids),
    )
    assert await _every_row(world.factory) == every_row
    served = replace(probe, at=probe.at if probe.served_at is None else probe.served_at)
    control = await _send(world, served, ADMIN_HEADERS)
    assert control.status_code != 404, control.text

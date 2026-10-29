"""The webhook authenticates each alert with ITS strategy's own secret (multi-user
design AD6; tasks.md D.2).

One shared secret meant that anyone holding it could post for any strategy. Now a
strategy stores the SHA-256 of its own secret (``strategies.webhook_secret_hash``,
migration 0033) and an alert is accepted only with that strategy's secret. The
order of the checks is part of the contract:

1. the source address, global and first, before anything of the body is read;
2. the body limit and the JSON, which need no strategy;
3. the strategy named by ``signal_type``, read ONCE by primary key;
4. the secret, compared in constant time with the stored hash.

An unknown strategy, a missing secret, a wrong secret and a strategy whose hash is
NULL all answer the same 401, so a caller who is not authenticated cannot probe
which ids exist.

Runs on a database migrated to ``head`` with Alembic, like the other ingress
tests: the strategy is a real row and an accepted alert is really stored.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.owner import OWNER_ID, secret_hash, seed_owner
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

ALLOWED_IP = "52.89.214.238"
DISALLOWED_IP = "203.0.113.9"
SECRET_A = "per-strategy-secret-a-7c1d"
SECRET_B = "per-strategy-secret-b-2e90"
# The setting still exists (0033 reads it) but ingress no longer consults it.
GLOBAL_SECRET = "the-old-global-secret-5f3a"
UNAUTHORIZED = {"detail": "unauthorized"}
ROUTER_LOGGER = "strategy_manager.signals.infrastructure.router"
LIMIT = 65_536


def _payload(strategy_id: UUID) -> dict[str, object]:
    return {
        "data": {"action": "buy", "contracts": "10", "position_size": "10"},
        "price": "0.5",
        "signal_param": "{}",
        "signal_type": str(strategy_id),
        "symbol": "STXUSDT.P",
        "time": "2026-10-29T10:15:30Z",
    }


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_per_strategy_secret") as url:
        yield url


@pytest.fixture
async def engine(head_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM jobs"))
        await conn.execute(text("DELETE FROM signals"))
        await conn.execute(text("DELETE FROM strategies"))
        await seed_owner(conn)
        await conn.execute(
            text(
                "INSERT INTO capital_pools "
                "(user_id, exchange, venue, settlement_currency, min_order_size) "
                "VALUES (:owner, 'bybit', 'usdt-m', 'USDT', 5) ON CONFLICT DO NOTHING"
            ),
            {"owner": OWNER_ID},
        )
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _global_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", GLOBAL_SECRET)


def _client_from(engine: AsyncEngine, ip: str) -> AsyncClient:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, client=(ip, 12345), raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    async with _client_from(engine, ALLOWED_IP) as ac:
        yield ac


@pytest.fixture
async def outsider(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    async with _client_from(engine, DISALLOWED_IP) as ac:
        yield ac


async def _register(
    engine: AsyncEngine,
    *,
    secret: str | None,
    archived: bool = False,
) -> UUID:
    strategy_id = uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO strategies (id, name, exchange, venue, settlement_currency, "
                "enabled, fill_mode, allowed_pairs, author_id, webhook_secret_hash, "
                "archived_at) VALUES (:id, :name, 'bybit', 'usdt-m', 'USDT', :enabled, "
                "'PARTIAL', ARRAY['STXUSDT'], :author, :hash, "
                "CASE WHEN :archived THEN now() END)"
            ),
            {
                "id": strategy_id,
                "name": f"strategy-{strategy_id}",
                "author": OWNER_ID,
                "hash": None if secret is None else secret_hash(secret),
                "enabled": not archived,
                "archived": archived,
            },
        )
    return strategy_id


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def _post(
    client: AsyncClient, strategy_id: UUID, secret: str | None
) -> Response:
    params = {} if secret is None else {"secret": secret}
    return await client.post("/webhook/tradingview", params=params, json=_payload(strategy_id))


async def _assert_nothing_stored(engine: AsyncEngine) -> None:
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


# ---------------------------------------------------------------------------
# The strategy's own secret is the one that works
# ---------------------------------------------------------------------------


async def test_an_alert_with_the_strategys_own_secret_is_accepted_and_enqueues_one_job(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)

    response = await _post(client, strategy_id, SECRET_A)

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert await _count(engine, "signals") == 1
    assert await _count(engine, "jobs") == 1


async def test_another_strategys_secret_is_refused_which_is_why_the_secret_is_per_strategy(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    strategy_a = await _register(engine, secret=SECRET_A)
    strategy_b = await _register(engine, secret=SECRET_B)

    crossed = await _post(client, strategy_a, SECRET_B)
    own = await _post(client, strategy_b, SECRET_B)

    assert (crossed.status_code, crossed.json()) == (401, UNAUTHORIZED)
    assert own.status_code == 200
    assert await _count(engine, "signals") == 1  # only B's own alert


async def test_the_old_global_secret_no_longer_opens_any_strategy(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)

    response = await _post(client, strategy_id, GLOBAL_SECRET)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
    await _assert_nothing_stored(engine)


# ---------------------------------------------------------------------------
# Four ways to fail, one answer
# ---------------------------------------------------------------------------


async def test_a_strategy_that_does_not_exist_is_401_not_422(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    response = await _post(client, uuid4(), GLOBAL_SECRET)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
    await _assert_nothing_stored(engine)


async def test_a_missing_secret_is_401(client: AsyncClient, engine: AsyncEngine) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)

    response = await _post(client, strategy_id, None)

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
    await _assert_nothing_stored(engine)


async def test_a_wrong_secret_is_401(client: AsyncClient, engine: AsyncEngine) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)

    response = await _post(client, strategy_id, "not-the-secret")

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
    await _assert_nothing_stored(engine)


async def test_a_strategy_with_no_hash_accepts_no_secret(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    strategy_id = await _register(engine, secret=None)

    responses = [
        await _post(client, strategy_id, secret)
        for secret in (None, "", GLOBAL_SECRET, SECRET_A)
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(401, UNAUTHORIZED)] * 4
    await _assert_nothing_stored(engine)


async def test_the_four_refusals_are_indistinguishable_to_the_caller(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    registered = await _register(engine, secret=SECRET_A)
    unhashed = await _register(engine, secret=None)

    refusals = [
        await _post(client, uuid4(), SECRET_A),  # unknown strategy
        await _post(client, registered, None),  # missing secret
        await _post(client, registered, SECRET_B),  # wrong secret
        await _post(client, unhashed, SECRET_A),  # no hash stored
    ]

    assert {r.status_code for r in refusals} == {401}
    assert len({(r.text, tuple(sorted(r.headers.items()))) for r in refusals}) == 1


async def test_a_refusal_writes_no_log_line_and_no_record_carries_a_secret_or_a_hash(
    client: AsyncClient, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)

    with caplog.at_level(logging.DEBUG):
        await _post(client, strategy_id, SECRET_B)
        await _post(client, uuid4(), SECRET_B)

    assert [r for r in caplog.records if r.name == ROUTER_LOGGER] == []
    everything = "\n".join(r.getMessage() for r in caplog.records)
    for forbidden in (SECRET_A, SECRET_B, secret_hash(SECRET_A), secret_hash(SECRET_B)):
        assert forbidden not in everything


async def test_the_rest_of_the_alert_is_judged_only_after_the_secret(
    client: AsyncClient, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    # TradingView's addresses are shared by every TradingView user, so passing the
    # address check proves nothing: only ``signal_type`` is read before the secret.
    strategy_id = await _register(engine, secret=SECRET_A)
    malformed = {k: v for k, v in _payload(strategy_id).items() if k != "symbol"}

    with caplog.at_level(logging.DEBUG):
        stranger = await client.post(
            "/webhook/tradingview", params={"secret": SECRET_B}, json=malformed
        )
    stranger_logs = [r for r in caplog.records if r.name == ROUTER_LOGGER]
    author = await client.post(
        "/webhook/tradingview", params={"secret": SECRET_A}, json=malformed
    )

    assert (stranger.status_code, stranger.json()) == (401, UNAUTHORIZED)
    assert stranger_logs == []
    assert author.status_code == 422
    await _assert_nothing_stored(engine)


# ---------------------------------------------------------------------------
# The order: address, then body, then the one strategy read, then the secret
# ---------------------------------------------------------------------------


class _CountingBody:
    def __init__(self, chunks: int) -> None:
        self.chunks = chunks
        self.pulled = 0

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[bytes]:
        for _ in range(self.chunks):
            self.pulled += 1
            yield b"x" * 1024


async def test_a_stranger_address_is_401_with_the_right_secret_and_none_of_the_body_is_read(
    outsider: AsyncClient, engine: AsyncEngine
) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)
    statements: list[str] = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )
    stream = _CountingBody(chunks=8)

    response = await outsider.post(
        "/webhook/tradingview", params={"secret": SECRET_A}, content=stream
    )
    own_alert = await outsider.post(
        "/webhook/tradingview", params={"secret": SECRET_A}, json=_payload(strategy_id)
    )

    assert (response.status_code, response.json()) == (401, UNAUTHORIZED)
    assert (own_alert.status_code, own_alert.json()) == (401, UNAUTHORIZED)
    assert stream.pulled == 0
    assert statements == []  # the address is judged before the database is touched
    await _assert_nothing_stored(engine)


@pytest.mark.parametrize(
    ("kwargs", "status"),
    [
        ({"content": b"x" * (LIMIT + 1), "headers": {"Content-Type": "application/json"}}, 413),
        ({"content": b"not json at all", "headers": {"Content-Type": "application/json"}}, 422),
    ],
    ids=["body-past-the-limit", "not-json"],
)
async def test_the_body_limit_and_the_json_are_judged_before_the_secret(
    client: AsyncClient, engine: AsyncEngine, kwargs: dict[str, object], status: int
) -> None:
    response = await client.post(
        "/webhook/tradingview", params={"secret": "wrong"}, **kwargs  # type: ignore[arg-type]
    )

    assert response.status_code == status
    await _assert_nothing_stored(engine)


async def test_authentication_reads_exactly_one_strategy_row_and_writes_nothing(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    strategy_id = await _register(engine, secret=SECRET_A)
    statements: list[str] = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )

    refused = await _post(client, strategy_id, SECRET_B)

    assert refused.status_code == 401
    assert len(statements) == 1
    assert statements[0].lstrip().upper().startswith("SELECT")
    assert "strategies" in statements[0]
    assert "webhook_secret_hash" in statements[0]
    await _assert_nothing_stored(engine)


# ---------------------------------------------------------------------------
# An archived strategy authenticates; processing is what refuses it
# ---------------------------------------------------------------------------


async def test_an_archived_strategys_correct_secret_is_accepted_at_ingress(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    """Operator-panel decision 11: ingress keeps no archived check. The refusal
    lives in processing (``_refuse_archived_strategy``, pinned in
    ``tests/signals/application/test_process_signal.py``)."""
    strategy_id = await _register(engine, secret=SECRET_A, archived=True)

    accepted = await _post(client, strategy_id, SECRET_A)
    refused = await _post(client, strategy_id, SECRET_B)

    assert accepted.status_code == 200
    assert (refused.status_code, refused.json()) == (401, UNAUTHORIZED)
    assert await _count(engine, "signals") == 1

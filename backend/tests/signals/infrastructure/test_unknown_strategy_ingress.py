"""The webhook refuses an alert whose strategy is not registered.

Runs on a database migrated to ``head`` with Alembic, not on the ORM-built test
schema: ``fk_signals_strategy`` exists ONLY in the migrations
(``0003_strategies_pools.py``), and the ORM column carries no ``ForeignKey``. On
the ORM schema the ``INSERT`` for an unregistered strategy simply succeeds, so a
test of the refusal would pass or fail for the wrong reason.

The app runs with ``raise_app_exceptions=False`` so an unhandled exception
surfaces as the 500 a real client would receive, and the test fails on that
status rather than on a traceback.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

ALLOWED_IP = "52.89.214.238"
SECRET = "test-webhook-secret-9xa"


def _payload(strategy_id: UUID, *, symbol: str = "STXUSDT.P") -> dict[str, object]:
    return {
        "data": {"action": "buy", "contracts": "10", "position_size": "10"},
        "price": "0.5",
        "signal_param": "{}",
        "signal_type": str(strategy_id),
        "symbol": symbol,
        "time": "2026-10-02T10:15:30Z",
    }


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_unknown_strategy_ingress") as url:
        yield url


@pytest.fixture
async def engine(head_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(head_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM jobs"))
        await conn.execute(text("DELETE FROM signals"))
        await conn.execute(text("DELETE FROM strategies"))
        await conn.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size) "
                "VALUES ('bybit', 'usdt-m', 'USDT', 5) ON CONFLICT DO NOTHING"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, client=(ALLOWED_IP, 12345), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register(engine: AsyncEngine, strategy_id: UUID, *, allowed: str = "STXUSDT") -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO strategies (id, name, exchange, venue, settlement_currency, "
                "enabled, fill_mode, allowed_pairs) VALUES (:id, :name, 'bybit', 'usdt-m', "
                "'USDT', true, 'PARTIAL', ARRAY[:pair])"
            ),
            {"id": strategy_id, "name": f"strategy-{strategy_id}", "pair": allowed},
        )


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def test_an_alert_for_an_unregistered_strategy_is_422_unknown_strategy_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    response = await client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=_payload(uuid4())
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "UNKNOWN_STRATEGY"
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


async def test_the_same_alert_replayed_is_refused_again_and_still_persists_nothing(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    payload = _payload(uuid4())

    first = await client.post("/webhook/tradingview", params={"secret": SECRET}, json=payload)
    second = await client.post("/webhook/tradingview", params={"secret": SECRET}, json=payload)

    assert (first.status_code, second.status_code) == (422, 422)
    assert second.json() == first.json()
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


async def test_a_valid_alert_after_a_refused_one_is_accepted(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    registered = uuid4()
    await _register(engine, registered)

    refused = await client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=_payload(uuid4())
    )
    accepted = await client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=_payload(registered)
    )

    assert refused.status_code == 422
    assert accepted.status_code == 200
    assert await _count(engine, "signals") == 1
    assert await _count(engine, "jobs") == 1


async def test_an_alert_for_a_registered_strategy_is_still_accepted_and_enqueues_one_job(
    client: AsyncClient, engine: AsyncEngine
) -> None:
    registered = uuid4()
    await _register(engine, registered, allowed="STXUSDT")

    response = await client.post(
        "/webhook/tradingview",
        params={"secret": SECRET},
        json=_payload(registered, symbol="STXUSDT.P"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["duplicate"] is False
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT id, symbol FROM signals"))).one()
    assert str(stored.id) == body["signal_id"]
    assert stored.symbol == "STXUSDT.P"
    assert await _count(engine, "jobs") == 1


async def test_the_refusal_logs_one_warning_and_no_error(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    strategy_id = uuid4()

    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/webhook/tradingview", params={"secret": SECRET}, json=_payload(strategy_id)
        )

    assert response.status_code == 422
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.levelno for r in loud] == [logging.WARNING]
    assert str(strategy_id) in loud[0].getMessage()
    assert loud[0].exc_info is None
    assert SECRET not in loud[0].getMessage()

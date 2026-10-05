"""The webhook refuses an alert whose numeric field is not a finite number.

Task 9qf.1. ``Decimal("NaN")`` and ``Decimal("Infinity")`` are values the
``Decimal`` constructor accepts without raising, so before this fix an alert
carrying one was parsed, stored and handed to the worker, where an opening order
priced at it raised ``decimal.InvalidOperation`` on every retry.

Runs on a database migrated to ``head`` with Alembic, like the other ingress
tests that need the production schema: the registered strategy is real, so an
alert that is NOT refused at the parse step is genuinely stored and the "no row,
no job" assertions cannot pass for the wrong reason.

The app runs with ``raise_app_exceptions=False`` so an unhandled exception
surfaces as the 500 a real client would receive, and a test fails on that status
rather than on a traceback.
"""

import copy
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any
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
SECRET = "test-webhook-secret-nf7"
ROUTER_LOGGER = "strategy_manager.signals.infrastructure.router"

FIELDS = ("price", "data.contracts", "data.position_size")


def _payload(strategy_id: UUID) -> dict[str, Any]:
    return {
        "data": {"action": "buy", "contracts": "10", "position_size": "10"},
        "price": "0.5",
        "signal_param": "{}",
        "signal_type": str(strategy_id),
        "symbol": "STXUSDT.P",
        "time": "2026-10-05T10:15:30Z",
    }


def _with(payload: dict[str, Any], field: str, value: str) -> dict[str, Any]:
    changed = copy.deepcopy(payload)
    target = changed["data"] if field.startswith("data.") else changed
    target[field.removeprefix("data.")] = value
    return changed


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_non_finite_alert_ingress") as url:
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


@pytest.fixture
async def strategy_id(engine: AsyncEngine) -> UUID:
    registered = uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO strategies (id, name, exchange, venue, settlement_currency, "
                "enabled, fill_mode, allowed_pairs) VALUES (:id, :name, 'bybit', 'usdt-m', "
                "'USDT', true, 'PARTIAL', ARRAY['STXUSDT'])"
            ),
            {"id": registered, "name": f"strategy-{registered}"},
        )
    return registered


async def _count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def _post(client: AsyncClient, payload: dict[str, Any]) -> Any:
    return await client.post("/webhook/tradingview", params={"secret": SECRET}, json=payload)


async def test_a_finite_alert_for_the_registered_strategy_is_stored_unchanged(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID
) -> None:
    response = await _post(client, _payload(strategy_id))

    assert response.status_code == 200
    async with engine.connect() as conn:
        stored = (await conn.execute(text("SELECT price, contracts FROM signals"))).one()
    assert str(stored.price).rstrip("0").rstrip(".") == "0.5"
    assert await _count(engine, "signals") == 1
    assert await _count(engine, "jobs") == 1


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
@pytest.mark.parametrize("field", FIELDS)
async def test_an_alert_with_a_non_finite_number_is_422_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, field: str, value: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), field, value))

    assert response.status_code == 422
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize("field", FIELDS)
async def test_the_refusal_names_the_field_and_never_echoes_the_value(
    client: AsyncClient, strategy_id: UUID, field: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), field, "NaN"))

    assert response.status_code == 422
    detail = str(response.json()["detail"])
    assert field in detail
    assert "NaN" not in detail


@pytest.mark.parametrize("field", FIELDS)
async def test_the_refusal_logs_exactly_one_warning_without_the_value_the_price_or_the_secret(
    client: AsyncClient, strategy_id: UUID, caplog: pytest.LogCaptureFixture, field: str
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _with(_payload(strategy_id), field, "NaN"))

    assert response.status_code == 422
    loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    message = loud[0].getMessage()
    assert field in message
    assert "refused" in message
    assert loud[0].exc_info is None
    assert "NaN" not in message
    assert "0.5" not in message
    assert SECRET not in message
    assert str(strategy_id) not in message

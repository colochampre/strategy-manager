"""Every refusal of a malformed alert leaves exactly one WARNING, and no value.

Task 9qf.6. TradingView shows the response of a webhook to nobody, so before
this task every refusal but two (a non-finite number, 9qf.1, and an unknown
strategy, unit 9xa) answered 422 and left no line anywhere.

The line is ``webhook alert refused: <field> <reason>``: a field name and a fixed
reason from the parser, never the payload, a price, a quantity, the secret or
any value the sender supplied. Each case that carries a distinctive value
asserts that the value appears in no log record.

An unauthenticated request is NOT logged: the endpoint faces the internet and a
line per scan would drown the log. An accepted and a duplicate alert write no
WARNING.

Runs on a database migrated to ``head`` with Alembic, like the other ingress
tests that need the production schema.
"""

import copy
import logging
from collections.abc import AsyncIterator, Callable, Iterator
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
from strategy_manager.shared.config import get_settings
from strategy_manager.signals.infrastructure import router as webhook_router
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

ALLOWED_IP = "52.89.214.238"
SECRET = "test-webhook-secret-ml6"
ROUTER_LOGGER = "strategy_manager.signals.infrastructure.router"
PREFIX = "webhook alert refused: "

Mutation = Callable[[dict[str, Any]], dict[str, Any]]

FIELDS = (
    "data.action",
    "data.contracts",
    "data.position_size",
    "price",
    "symbol",
    "signal_type",
    "time",
)
NUMERIC_FIELDS = ("data.contracts", "data.position_size", "price")
STRING_FIELDS = ("data.action", "symbol", "signal_type", "time")


def _payload(strategy_id: UUID) -> dict[str, Any]:
    return {
        "data": {"action": "buy", "contracts": "10", "position_size": "10"},
        "price": "0.5",
        "signal_param": "{}",
        "signal_type": str(strategy_id),
        "symbol": "STXUSDT.P",
        "time": "2026-10-05T10:15:30Z",
    }


def _set(path: str, value: Any) -> Mutation:
    def mutate(payload: dict[str, Any]) -> dict[str, Any]:
        changed = copy.deepcopy(payload)
        target = changed["data"] if path.startswith("data.") else changed
        target[path.removeprefix("data.")] = value
        return changed

    return mutate


def _without(path: str) -> Mutation:
    def mutate(payload: dict[str, Any]) -> dict[str, Any]:
        changed = copy.deepcopy(payload)
        target = changed["data"] if path.startswith("data.") else changed
        del target[path.removeprefix("data.")]
        return changed

    return mutate


def _case(mutation: Mutation, reason: str, marker: str | None) -> Any:
    return pytest.param(mutation, reason, marker, id=reason)


# (mutation, the exact text after the prefix, a value that must reach no record)
CASES = [
    _case(_without("data"), "data is missing or not an object", None),
    _case(_set("data", "MARKER-DATA"), "data is missing or not an object", "MARKER-DATA"),
    *[_case(_without(f), f"{f} is missing", None) for f in FIELDS],
    *[_case(_set(f, 4242.4242), f"{f} is not a string", "4242.4242") for f in NUMERIC_FIELDS],
    *[
        _case(_set(f, "MARKER-DECIMAL"), f"{f} is not a valid decimal string", "MARKER-DECIMAL")
        for f in NUMERIC_FIELDS
    ],
    *[_case(_set(f, ""), f"{f} is empty or not a string", None) for f in STRING_FIELDS],
    *[
        _case(_set(f, 987654), f"{f} is empty or not a string", "987654")
        for f in STRING_FIELDS
    ],
    _case(
        _set("signal_type", "MARKER-NOT-A-UUID"),
        "signal_type is not a valid UUID",
        "MARKER-NOT-A-UUID",
    ),
]


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_malformed_alert_logging") as url:
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


async def _post(
    client: AsyncClient, payload: dict[str, Any], secret: str = SECRET
) -> Response:
    return await client.post("/webhook/tradingview", params={"secret": secret}, json=payload)


def _loud(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize(("mutation", "reason", "marker"), CASES)
async def test_a_refused_alert_is_422_and_leaves_exactly_one_warning_naming_the_reason(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    mutation: Mutation,
    reason: str,
    marker: str | None,
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, mutation(_payload(strategy_id)))

    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == PREFIX + reason
    assert loud[0].exc_info is None
    if marker is not None:
        assert marker not in loud[0].getMessage()
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize(
    ("mutation", "marker"),
    [pytest.param(c.values[0], c.values[2], id=c.values[1]) for c in CASES if c.values[2]],
)
async def test_no_log_record_carries_the_value_the_sender_supplied(
    client: AsyncClient,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    mutation: Mutation,
    marker: str,
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, mutation(_payload(strategy_id)))

    assert response.status_code == 422
    assert marker not in caplog.text
    for record in caplog.records:
        assert marker not in record.getMessage()
        assert marker not in str(record.args)


async def test_the_decimal_refusal_detail_still_carries_the_value_but_the_log_does_not(
    client: AsyncClient, strategy_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _set("price", "MARKER-DECIMAL")(_payload(strategy_id)))

    assert response.status_code == 422
    assert "price is not a valid decimal string" in str(response.json()["detail"])
    assert "MARKER-DECIMAL" not in caplog.text


async def test_a_blank_idempotency_key_is_422_and_leaves_exactly_one_warning(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(webhook_router, "derive_idempotency_key", lambda alert: "  ")

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _payload(strategy_id))

    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == PREFIX + "idempotency key is missing"
    assert await _count(engine, "signals") == 0


async def test_an_unknown_strategy_leaves_exactly_one_warning(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _payload(uuid4()))

    assert response.status_code == 422
    loud = _loud(caplog)
    assert len(loud) == 1
    assert loud[0].levelno == logging.WARNING
    assert loud[0].getMessage().startswith(PREFIX + "no strategy is registered")


async def test_an_accepted_alert_and_a_duplicate_write_no_warning(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        first = await _post(client, _payload(strategy_id))
        second = await _post(client, _payload(strategy_id))

    assert (first.status_code, first.json()["duplicate"]) == (200, False)
    assert (second.status_code, second.json()["duplicate"]) == (200, True)
    assert await _count(engine, "signals") == 1
    assert _loud(caplog) == []


async def test_an_unauthenticated_request_is_401_and_writes_no_line_at_all(
    client: AsyncClient, strategy_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _payload(strategy_id), secret="wrong-secret")

    assert response.status_code == 401
    assert [r for r in caplog.records if r.name == ROUTER_LOGGER] == []
    assert _loud(caplog) == []

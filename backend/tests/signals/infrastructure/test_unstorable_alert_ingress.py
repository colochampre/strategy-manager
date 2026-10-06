"""The webhook refuses, as a 422, what the ``signals`` table would refuse.

Task 9qf.5. Migration 0002 puts the CHECK ``price > 0`` on the price and declares
``price``, ``contracts`` and ``position_size`` as ``NUMERIC(38, 18)``. A value
either of those refuses used to reach the insert, nothing caught the refusal and
the webhook answered an unhandled 500, which is what the operator alerts are for.
A request body that is not valid JSON, or not an object, did the same.

Runs on a database migrated to ``head`` with Alembic, like
``test_non_finite_alert_ingress.py``: the registered strategy is real, so an alert
that is NOT refused is genuinely stored and the "no row, no job" assertions cannot
pass for the wrong reason.

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
from tests.pg_head_schema import migrated_head_database

pytestmark = pytest.mark.integration

ALLOWED_IP = "52.89.214.238"
SECRET = "test-webhook-secret-us5"
ROUTER_LOGGER = "strategy_manager.signals.infrastructure.router"

FIELDS = ("price", "data.contracts", "data.position_size")
SIGNED_FIELDS = ("data.contracts", "data.position_size")

TWENTY_ONE_DIGITS = "100000000000000000000"
JSON_HEADERS = {"content-type": "application/json"}


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
    with migrated_head_database("strategy_manager_test_unstorable_alert_ingress") as url:
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


async def _post(client: AsyncClient, payload: dict[str, Any]) -> Response:
    return await client.post("/webhook/tradingview", params={"secret": SECRET}, json=payload)


async def _post_raw(client: AsyncClient, body: bytes) -> Response:
    return await client.post(
        "/webhook/tradingview", params={"secret": SECRET}, content=body, headers=JSON_HEADERS
    )


def _loud(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("value", ["0", "-1", "-0.5", "0.0"])
async def test_a_price_that_is_not_above_zero_is_422_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, value: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), "price", value))

    assert response.status_code == 422
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


async def test_the_price_refusal_names_the_field_and_never_echoes_the_value(
    client: AsyncClient, strategy_id: UUID
) -> None:
    response = await _post(client, _with(_payload(strategy_id), "price", "-7123.5"))

    assert response.status_code == 422
    detail = str(response.json()["detail"])
    assert "price" in detail
    assert "7123" not in detail


async def test_the_price_refusal_logs_exactly_one_warning_without_the_value(
    client: AsyncClient, strategy_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _with(_payload(strategy_id), "price", "-7123.5"))

    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == "webhook alert refused: price is not above zero"
    assert loud[0].exc_info is None
    assert "7123" not in loud[0].getMessage()


@pytest.mark.parametrize("value", ["0", "-1", "-0.5"])
@pytest.mark.parametrize("field", SIGNED_FIELDS)
async def test_contracts_and_position_size_accept_zero_and_negative_because_the_database_does(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, field: str, value: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), field, value))

    assert response.status_code == 200
    assert await _count(engine, "signals") == 1
    assert await _count(engine, "jobs") == 1


@pytest.mark.parametrize("value", [TWENTY_ONE_DIGITS, "1E+20"])
@pytest.mark.parametrize("field", FIELDS)
async def test_a_number_with_more_integer_digits_than_the_column_holds_is_422_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, field: str, value: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), field, value))

    assert response.status_code == 422
    detail = str(response.json()["detail"])
    assert field in detail
    assert value not in detail
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize("value", ["0E+999999", "1E-20000", "0." + "1" * 17000])
@pytest.mark.parametrize("field", SIGNED_FIELDS)
async def test_a_number_whose_exponent_the_column_cannot_encode_is_422_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, field: str, value: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), field, value))

    assert response.status_code == 422
    assert field in str(response.json()["detail"])
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize("value", ["0E+20", "1E-16000"])
async def test_an_extreme_exponent_the_column_can_still_encode_is_stored(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, value: str
) -> None:
    response = await _post(client, _with(_payload(strategy_id), "data.contracts", value))

    assert response.status_code == 200
    assert await _count(engine, "signals") == 1


@pytest.mark.parametrize("field", FIELDS)
async def test_the_range_refusal_logs_exactly_one_warning_without_the_value(
    client: AsyncClient, strategy_id: UUID, caplog: pytest.LogCaptureFixture, field: str
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post(client, _with(_payload(strategy_id), field, TWENTY_ONE_DIGITS))

    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == (
        f"webhook alert refused: {field} is out of range for the stored precision"
    )
    assert TWENTY_ONE_DIGITS not in loud[0].getMessage()


async def test_the_largest_number_the_column_holds_is_stored(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID
) -> None:
    payload = _with(_payload(strategy_id), "price", "99999999999999999999")

    response = await _post(client, payload)

    assert response.status_code == 200
    assert await _count(engine, "signals") == 1


@pytest.mark.parametrize(
    "body", [b'{"price": "SECRETMARKER', b"", b"not json at all", b"{'price': 1}", b"\xff\xfe"]
)
async def test_a_body_that_is_not_valid_json_is_422_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, body: bytes
) -> None:
    response = await _post_raw(client, body)

    assert response.status_code == 422
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize("body", [b"[]", b'[{"price": "1"}]', b'"alert"', b"5", b"null", b"true"])
async def test_a_json_body_that_is_not_an_object_is_422_and_persists_nothing(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, body: bytes
) -> None:
    response = await _post_raw(client, body)

    assert response.status_code == 422
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


async def test_a_body_that_is_not_valid_json_logs_exactly_one_warning_without_the_body(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post_raw(client, b'{"price": "SECRETMARKER')

    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == "webhook alert refused: body is not valid JSON"
    assert loud[0].exc_info is None
    assert "SECRETMARKER" not in loud[0].getMessage()


@pytest.mark.parametrize("body", [b"[]", b'"SECRETMARKER"', b"5", b"null"])
async def test_a_json_body_that_is_not_an_object_logs_exactly_one_warning_without_the_body(
    client: AsyncClient, caplog: pytest.LogCaptureFixture, body: bytes
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = await _post_raw(client, body)

    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == "webhook alert refused: body is not a JSON object"
    assert "SECRETMARKER" not in loud[0].getMessage()

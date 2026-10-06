"""The webhook refuses, as a 422, a body the ``signals`` table cannot hold.

Task 9qf.7. A body can be authenticated, be valid JSON, have the alert's shape and
still be impossible to STORE: the insert (or the idempotency key before it) raises,
nothing catches it and the webhook answered an unhandled 500. Observed on this
route against a database migrated to ``head``, before the fix:

* a NUL character (``\\u0000``) in any string of the body or in an object key: 500
  (``text`` and ``jsonb`` cannot hold it);
* a lone surrogate (``\\ud800``) in the same places: 500 (``jsonb`` refuses the
  escape, ``text`` the encoding, and the idempotency key cannot encode it);
* ``NaN``, ``Infinity``, ``-Infinity`` and ``1e999`` as the value of a key the
  alert parser does not read: 500 (JSON has no such number);
* a body nested about 3,000 levels deep or more: 500, because the JSON parser's
  recursion overflows before the alert parser sees it.

The bodies are explicit bytes, so each test sends exactly the escape it means and
asserts it was sent: ``json.dumps`` would otherwise escape or refuse it first.

Runs on a database migrated to ``head`` with Alembic, like
``test_unstorable_alert_ingress.py``: the registered strategy is real, so an alert
that is NOT refused is genuinely stored and the "no row, no job" assertions cannot
pass for the wrong reason. The app runs with ``raise_app_exceptions=False`` so an
unhandled exception surfaces as the 500 a real client would receive.
"""

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
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
SECRET = "test-webhook-secret-9qf7"
ROUTER_LOGGER = "strategy_manager.signals.infrastructure.router"
PREFIX = "webhook alert refused: "
JSON_HEADERS = {"content-type": "application/json"}

CHARACTER_LINE = PREFIX + "body contains a character that cannot be stored"
NUMBER_LINE = PREFIX + "body contains a number that is not finite"
DEPTH_LINE = PREFIX + "body is nested too deeply"

# The JSON text of each bad string, as an escape: the bytes sent contain the six
# characters ``\u0000`` or ``\ud800``, never a raw NUL byte.
NUL = r"\u0000"
SURROGATE = r"\ud800"
BAD_ESCAPES = [pytest.param(NUL, id="nul"), pytest.param(SURROGATE, id="lone-surrogate")]
NON_FINITE_LITERALS = ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"]

# The deepest body the webhook accepts (the body is level 1, ``data`` level 2).
BOUND = 64


def _body(
    strategy_id: UUID,
    *,
    action: str = '"buy"',
    symbol: str = '"STXUSDT.P"',
    signal_type: str | None = None,
    time: str = '"2026-10-05T10:15:30Z"',
    signal_param: str = '"{}"',
    inner: str = "",
    extra: str = "",
) -> bytes:
    """The alert as JSON text. Each argument is a JSON fragment, inserted as given."""

    registered = signal_type if signal_type is not None else f'"{strategy_id}"'
    return (
        '{"data":{"action":' + action + ',"contracts":"10","position_size":"10"' + inner + "},"
        '"price":"0.5","signal_param":' + signal_param + ',"signal_type":' + registered
        + ',"symbol":' + symbol + ',"time":' + time + extra + "}"
    ).encode("ascii")


def _nested(levels: int, *, objects: bool) -> str:
    """JSON text of ``levels`` nested containers."""

    if objects:
        return '{"a":' * (levels - 1) + "{}" + "}" * (levels - 1)
    return "[" * levels + "]" * levels


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_unstorable_body_ingress") as url:
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


async def _post(client: AsyncClient, body: bytes) -> Response:
    return await client.post(
        "/webhook/tradingview", params={"secret": SECRET}, content=body, headers=JSON_HEADERS
    )


def _loud(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def _placements(strategy_id: UUID, bad: str) -> dict[str, bytes]:
    """The same bad JSON string fragment in every place a body can carry one."""

    string = f'"a{bad}b"'
    return {
        "data.action": _body(strategy_id, action=string),
        "symbol": _body(strategy_id, symbol=string),
        "signal_type": _body(strategy_id, signal_type=string),
        "time": _body(strategy_id, time=string),
        "signal_param": _body(strategy_id, signal_param=string),
        "extra top-level key": _body(strategy_id, extra=f',"x":{string}'),
        "extra key inside data": _body(strategy_id, inner=f',"x":{string}'),
        "nested object value": _body(strategy_id, extra=f',"x":{{"y":{{"z":{string}}}}}'),
        "array element": _body(strategy_id, extra=f',"x":["ok",[{string}]]'),
        "top-level object key": _body(strategy_id, extra=f',"k{bad}":1'),
        "nested object key": _body(strategy_id, extra=f',"x":{{"k{bad}":1}}'),
        "key of an object in an array": _body(strategy_id, extra=f',"x":[{{"k{bad}":1}}]'),
    }


PLACES = list(_placements(uuid4(), NUL))


def _assert_nothing_stored_and_one_line(
    response: Response, caplog: pytest.LogCaptureFixture, line: str
) -> None:
    assert response.status_code == 422
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == line
    assert loud[0].exc_info is None


@pytest.mark.parametrize("bad", BAD_ESCAPES)
@pytest.mark.parametrize("place", PLACES)
async def test_a_nul_or_a_lone_surrogate_anywhere_in_the_body_is_422_and_persists_nothing(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    place: str,
    bad: str,
) -> None:
    body = _placements(strategy_id, bad)[place]
    assert bad.encode("ascii") in body
    assert b"\x00" not in body

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    _assert_nothing_stored_and_one_line(response, caplog, CHARACTER_LINE)
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize("bad", BAD_ESCAPES)
async def test_the_character_refusal_never_echoes_what_the_sender_supplied(
    client: AsyncClient, strategy_id: UUID, caplog: pytest.LogCaptureFixture, bad: str
) -> None:
    body = _body(strategy_id, extra=f',"MARKER-KEY{bad}":"MARKER-VALUE"')

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    assert response.status_code == 422
    for shown in (str(response.json()["detail"]), caplog.text):
        assert "MARKER" not in shown
    assert "body" in str(response.json()["detail"])


@pytest.mark.parametrize("literal", NON_FINITE_LITERALS)
async def test_a_number_that_is_not_finite_in_the_stored_body_is_422_and_persists_nothing(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    literal: str,
) -> None:
    bodies = [
        _body(strategy_id, extra=f',"x":{literal}'),
        _body(strategy_id, extra=f',"x":[{literal}]'),
        _body(strategy_id, extra=f',"x":{{"y":{literal}}}'),
        _body(strategy_id, inner=f',"x":{literal}'),
    ]

    for body in bodies:
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            response = await _post(client, body)

        _assert_nothing_stored_and_one_line(response, caplog, NUMBER_LINE)
        assert literal not in str(response.json()["detail"])
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


@pytest.mark.parametrize("objects", [False, True], ids=["arrays", "objects"])
@pytest.mark.parametrize("levels", [BOUND, 1_000, 2_000, 10_000, 100_000])
async def test_a_body_nested_past_the_bound_is_422_and_persists_nothing(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    levels: int,
    objects: bool,
) -> None:
    # The extra value is level 2, so ``levels`` containers make a body ``levels + 1`` deep:
    # 64 containers is one past the bound. 10,000 and 100,000 overflow the JSON
    # parser itself, which the route catches; the rest reach the domain walk.
    body = _body(strategy_id, extra=',"x":' + _nested(levels, objects=objects))

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    _assert_nothing_stored_and_one_line(response, caplog, DEPTH_LINE)
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


async def test_a_body_nested_beyond_the_json_parser_names_the_body_and_echoes_nothing(
    client: AsyncClient, strategy_id: UUID
) -> None:
    body = _body(strategy_id, extra=',"x":' + _nested(100_000, objects=False))

    response = await _post(client, body)

    assert response.status_code == 422
    assert str(response.json()["detail"]) == "body is nested too deeply"


@pytest.mark.parametrize("objects", [False, True], ids=["arrays", "objects"])
async def test_a_body_at_the_depth_bound_is_accepted_stored_and_enqueued(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    objects: bool,
) -> None:
    body = _body(strategy_id, extra=',"x":' + _nested(BOUND - 1, objects=objects))

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    assert response.status_code == 200
    assert _loud(caplog) == []
    assert await _count(engine, "signals") == 1
    assert await _count(engine, "jobs") == 1


async def test_the_valid_alert_is_stored_unchanged_and_keeps_its_idempotency_key(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _body(
        strategy_id,
        symbol='"STX\\u00e9USDT.P"',
        signal_param='"{}"',
        extra=(
            ',"note":"caf\\u00e9 \\u4e2d\\u6587 \\ud83d\\ude80 \\\\u0000"'
            ',"extra":{"k":[1,2.5,null]}'
        ),
    )
    assert b"\\\\u0000" in body

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert _loud(caplog) == []
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT raw_payload, idempotency_key, symbol FROM signals")
            )
        ).one()
    assert row.raw_payload == json.loads(body)
    assert row.raw_payload["signal_param"] == "{}"
    assert row.symbol == "STXéUSDT.P"
    # sha256 of "<signal_type>|<time>|buy|10|10", fixed before this task: an
    # accepted alert keeps exactly the key it always had.
    expected = hashlib.sha256(
        f"{strategy_id}|2026-10-05T10:15:30Z|buy|10|10".encode()
    ).hexdigest()
    assert row.idempotency_key == expected
    assert await _count(engine, "jobs") == 1

    again = await _post(client, body)
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert await _count(engine, "signals") == 1


async def test_a_literal_backslash_u0000_is_text_not_a_nul_and_is_accepted(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID
) -> None:
    body = _body(strategy_id, extra=',"x":"\\\\u0000"')
    assert b'"\\\\u0000"' in body

    response = await _post(client, body)

    assert response.status_code == 200
    assert await _count(engine, "signals") == 1


@pytest.mark.parametrize(
    "literal",
    [
        "1e308",
        "-1e308",
        "1e-999",
        "-0.0",
        pytest.param("9" * 4000, id="4000-digit-integer"),
    ],
)
async def test_a_finite_number_in_the_stored_body_is_accepted(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, literal: str
) -> None:
    response = await _post(client, _body(strategy_id, extra=f',"x":{literal}'))

    assert response.status_code == 200
    assert await _count(engine, "signals") == 1

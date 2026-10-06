"""The webhook refuses, as a 413, a body larger than 64 KiB, in the application.

Task 9qf.8, owner decision 47. Nothing bounded the size of a webhook body: the
route read it whole with ``request.json()`` and a body with an 8 MB string was
stored with a 200. The limit is 65,536 bytes, enforced here and not at the edge:

* a body of exactly 65,536 bytes is within the limit and one byte more is refused;
* the refusal answers 413, stores nothing (no signal, no job) and writes ONE
  WARNING with a fixed reason that carries nothing the sender supplied, the
  declared ``Content-Length`` included;
* the body is never read whole and then measured. A declared length past the limit
  is refused before any of the body is read, and a body with no declared length
  stops being read at the first chunk that takes the count past the limit;
* the count of bytes that actually arrive is the authority. A ``Content-Length``
  that is absent, not a number or smaller than what arrives never lets a larger
  body through and never raises;
* authentication stays first: an unauthenticated request is a 401 and none of its
  body is read.

What the test transport does with the header. ``httpx.ASGITransport`` drives the
application's ``receive`` straight from the request's stream, one chunk per call,
and checks nothing about ``Content-Length``: a header the test passes is delivered
as written, whatever the body is, and a request built from an async generator
carries no ``Content-Length`` at all (``Transfer-Encoding: chunked``). So a
missing, a lying and an unparsable header can all be driven here. A real server
(uvicorn on h11) does NOT deliver the unparsable or the lying ones: see the task
in ``tasks.md`` for what was observed.

The size constants below are literals on purpose: they pin the owner's number and
do not move if the production constant is edited.

Runs on a database migrated to ``head`` with Alembic, like
``test_unstorable_body_ingress.py``: a registered strategy is real, so an alert
that is not refused is genuinely stored and the "no row, no job" assertions cannot
pass for the wrong reason.
"""

import json
import logging
from collections.abc import AsyncIterable, AsyncIterator, Iterator
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
SECRET = "test-webhook-secret-9qf8"
ROUTER_LOGGER = "strategy_manager.signals.infrastructure.router"
PREFIX = "webhook alert refused: "
JSON_HEADERS = {"content-type": "application/json"}

LIMIT = 65_536
TOO_LARGE_LINE = PREFIX + "body is larger than 65536 bytes"
TOO_LARGE_DETAIL = "request body is larger than 65536 bytes"
CHUNK = 1_024


class CountingBody:
    """An async request body that records how many chunks the application pulled."""

    def __init__(self, body: bytes, chunk: int = CHUNK) -> None:
        self.chunks = [body[i : i + chunk] for i in range(0, len(body), chunk)]
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for piece in self.chunks:
            self.pulled += 1
            yield piece


def _body(strategy_id: UUID, *, extra: str = "") -> bytes:
    """A valid alert as JSON text; ``extra`` is a JSON fragment inserted as given."""

    return (
        '{"data":{"action":"buy","contracts":"10","position_size":"10"},'
        f'"price":"0.5","signal_param":"{{}}","signal_type":"{strategy_id}",'
        '"symbol":"STXUSDT.P","time":"2026-10-05T10:15:30Z"' + extra + "}"
    ).encode("ascii")


def _alert_of_size(strategy_id: UUID, size: int, *, marker: str = "") -> bytes:
    """A valid alert of exactly ``size`` bytes: an extra string value pads it."""

    bare = _body(strategy_id, extra=',"pad":""')
    padding = marker + "a" * (size - len(bare) - len(marker))
    body = _body(strategy_id, extra=f',"pad":"{padding}"')
    assert len(body) == size
    return body


@pytest.fixture(scope="module")
def head_database_url() -> Iterator[str]:
    with migrated_head_database("strategy_manager_test_webhook_body_limit") as url:
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
    client: AsyncClient,
    content: bytes | AsyncIterable[bytes],
    *,
    headers: dict[str, str] | None = None,
    secret: str | None = SECRET,
) -> Response:
    params = {} if secret is None else {"secret": secret}
    return await client.post(
        "/webhook/tradingview",
        params=params,
        content=content,
        headers={**JSON_HEADERS, **(headers or {})},
    )


def _loud(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


async def _assert_refused_as_too_large(
    response: Response, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    assert response.status_code == 413
    assert response.json() == {"detail": TOO_LARGE_DETAIL}
    loud = _loud(caplog)
    assert [(r.name, r.levelno) for r in loud] == [(ROUTER_LOGGER, logging.WARNING)]
    assert loud[0].getMessage() == TOO_LARGE_LINE
    assert loud[0].exc_info is None
    assert await _count(engine, "signals") == 0
    assert await _count(engine, "jobs") == 0


# ---------------------------------------------------------------------------
# The limit itself, with a declared Content-Length
# ---------------------------------------------------------------------------


async def test_a_body_one_byte_past_the_limit_is_413_and_persists_nothing(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _alert_of_size(strategy_id, LIMIT + 1)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    assert response.request.headers["content-length"] == str(LIMIT + 1)
    await _assert_refused_as_too_large(response, engine, caplog)


async def test_a_body_of_exactly_the_limit_is_accepted_and_stored_unchanged(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _alert_of_size(strategy_id, LIMIT)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    assert response.request.headers["content-length"] == str(LIMIT)
    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert _loud(caplog) == []
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT raw_payload FROM signals"))).one()
    assert row.raw_payload == json.loads(body)
    assert await _count(engine, "jobs") == 1


async def test_a_body_far_past_the_limit_is_413_and_persists_nothing(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The case that was observed: 8 MB stored with a 200.
    body = _alert_of_size(strategy_id, 8 * 1024 * 1024)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    await _assert_refused_as_too_large(response, engine, caplog)


async def test_an_ordinary_alert_is_accepted_with_the_idempotency_key_it_always_had(
    client: AsyncClient, engine: AsyncEngine, strategy_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    body = _body(strategy_id)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)
        again = await _post(client, body)

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert again.status_code == 200
    assert again.json()["duplicate"] is True
    assert _loud(caplog) == []
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT raw_payload FROM signals"))).one()
    assert row.raw_payload == json.loads(body)
    assert await _count(engine, "signals") == 1


# ---------------------------------------------------------------------------
# A declared length past the limit is refused before any of the body is read
# ---------------------------------------------------------------------------


async def test_a_declared_length_past_the_limit_is_refused_before_any_of_the_body_is_read(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = CountingBody(_alert_of_size(strategy_id, 1024 * 1024))

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, stream, headers={"content-length": str(1024 * 1024)})

    assert response.request.headers["content-length"] == str(1024 * 1024)
    assert stream.pulled == 0
    await _assert_refused_as_too_large(response, engine, caplog)


# ---------------------------------------------------------------------------
# No declared length: the body is read in chunks and the count stops it
# ---------------------------------------------------------------------------


async def test_a_streamed_body_past_the_limit_stops_being_read_at_the_limit(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = CountingBody(_alert_of_size(strategy_id, 4 * 1024 * 1024))

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, stream)

    # The transport really sent no length: the count is the only thing that can stop it.
    assert "content-length" not in response.request.headers
    assert response.request.headers["transfer-encoding"] == "chunked"
    # 64 chunks of 1,024 bytes are exactly the limit and are within it; the 65th is
    # the first to take the count past it, and nothing after it is pulled.
    assert stream.pulled == LIMIT // CHUNK + 1
    assert stream.pulled < len(stream.chunks)
    await _assert_refused_as_too_large(response, engine, caplog)


async def test_a_streamed_body_whose_first_chunk_is_already_past_the_limit_is_refused(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = CountingBody(_alert_of_size(strategy_id, LIMIT + 10), chunk=LIMIT + 10)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, stream)

    assert stream.pulled == 1
    await _assert_refused_as_too_large(response, engine, caplog)


async def test_a_streamed_body_of_exactly_the_limit_is_accepted_and_stored_unchanged(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _alert_of_size(strategy_id, LIMIT)
    stream = CountingBody(body)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, stream)

    assert "content-length" not in response.request.headers
    assert response.status_code == 200
    assert stream.pulled == len(stream.chunks)
    assert _loud(caplog) == []
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT raw_payload FROM signals"))).one()
    assert row.raw_payload == json.loads(body)


# ---------------------------------------------------------------------------
# The header is only a shortcut: what arrives is the authority
# ---------------------------------------------------------------------------

# A header the application cannot trust: it understates what arrives, is not a
# number, or cannot be read as one. None of them may let a larger body through or
# raise.
UNTRUSTWORTHY_HEADERS = [
    pytest.param("100", id="lies-low"),
    pytest.param("0", id="zero"),
    pytest.param("-5", id="negative"),
    pytest.param("abc", id="not-a-number"),
    pytest.param("", id="empty"),
    pytest.param("1e9", id="exponent"),
    pytest.param("12 34", id="two-numbers"),
    pytest.param("9" * 5000, id="5000-digits"),
]


@pytest.mark.parametrize("declared", UNTRUSTWORTHY_HEADERS)
async def test_an_untrustworthy_content_length_never_lets_a_larger_body_through(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    declared: str,
) -> None:
    body = _alert_of_size(strategy_id, LIMIT + 1)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body, headers={"content-length": declared})

    assert response.request.headers["content-length"] == declared
    await _assert_refused_as_too_large(response, engine, caplog)


@pytest.mark.parametrize("declared", UNTRUSTWORTHY_HEADERS)
async def test_an_untrustworthy_content_length_does_not_stop_a_streamed_body_at_the_limit(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    declared: str,
) -> None:
    stream = CountingBody(_alert_of_size(strategy_id, 4 * 1024 * 1024))

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, stream, headers={"content-length": declared})

    assert stream.pulled == LIMIT // CHUNK + 1
    await _assert_refused_as_too_large(response, engine, caplog)


@pytest.mark.parametrize("declared", UNTRUSTWORTHY_HEADERS)
async def test_an_untrustworthy_content_length_does_not_refuse_a_body_within_the_limit(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    declared: str,
) -> None:
    # The count is the authority in both directions: a body that fits is a body that fits.
    body = _alert_of_size(strategy_id, LIMIT)

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body, headers={"content-length": declared})

    assert response.status_code == 200
    assert _loud(caplog) == []
    assert await _count(engine, "signals") == 1


# ---------------------------------------------------------------------------
# One warning, a fixed text, and nothing the sender supplied
# ---------------------------------------------------------------------------


async def test_the_refusal_echoes_nothing_the_sender_supplied(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _alert_of_size(strategy_id, LIMIT + 1, marker="MARKER-OVERSIZE")
    declared = "7654321"

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body, headers={"content-length": declared})

    await _assert_refused_as_too_large(response, engine, caplog)
    for shown in (response.text, caplog.text):
        assert "MARKER" not in shown
        assert declared not in shown
        assert str(len(body)) not in shown


@pytest.mark.parametrize("streamed", [False, True], ids=["declared", "streamed"])
async def test_each_refusal_writes_exactly_one_warning(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    streamed: bool,
) -> None:
    body = _alert_of_size(strategy_id, 3 * LIMIT)
    content: bytes | AsyncIterable[bytes] = CountingBody(body) if streamed else body

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, content)

    await _assert_refused_as_too_large(response, engine, caplog)
    assert [r for r in caplog.records if r.name == ROUTER_LOGGER] == _loud(caplog)


# ---------------------------------------------------------------------------
# The refusals that already existed are unchanged for a body under the limit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "line", "detail"),
    [
        pytest.param(
            b'{"data": ', "body is not valid JSON", "request body is not valid JSON", id="truncated"
        ),
        pytest.param(
            b"\xff\xfe\x00{", "body is not valid JSON", "request body is not valid JSON",
            id="undecodable",
        ),
        pytest.param(b"", "body is not valid JSON", "request body is not valid JSON", id="empty"),
        pytest.param(b"[]", "body is not a JSON object", "payload is not a JSON object", id="list"),
        pytest.param(
            b"null", "body is not a JSON object", "payload is not a JSON object", id="null"
        ),
        pytest.param(
            b'{"x":' + b"[" * 10_000 + b"]" * 10_000 + b"}",
            "body is nested too deeply",
            "body is nested too deeply",
            id="parser-overflow",
        ),
    ],
)
async def test_the_existing_refusals_still_answer_422_for_a_body_under_the_limit(
    client: AsyncClient,
    engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
    body: bytes,
    line: str,
    detail: str,
) -> None:
    assert len(body) < LIMIT

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, body)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    loud = _loud(caplog)
    assert [(r.name, r.levelno, r.getMessage()) for r in loud] == [
        (ROUTER_LOGGER, logging.WARNING, PREFIX + line)
    ]
    assert await _count(engine, "signals") == 0


# ---------------------------------------------------------------------------
# Authentication stays first: an unauthenticated request is never read
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("secret", ["wrong-secret", None], ids=["wrong-secret", "no-secret"])
@pytest.mark.parametrize("declared", [None, str(8 * 1024 * 1024)], ids=["streamed", "declared"])
async def test_an_unauthenticated_request_is_401_and_none_of_its_body_is_read(
    client: AsyncClient,
    engine: AsyncEngine,
    strategy_id: UUID,
    caplog: pytest.LogCaptureFixture,
    secret: str | None,
    declared: str | None,
) -> None:
    stream = CountingBody(_alert_of_size(strategy_id, 2 * LIMIT))
    headers = None if declared is None else {"content-length": declared}

    with caplog.at_level(logging.DEBUG):
        response = await _post(client, stream, headers=headers, secret=secret)

    assert response.status_code == 401
    assert stream.pulled == 0
    assert [r for r in caplog.records if r.name == ROUTER_LOGGER] == []
    assert _loud(caplog) == []
    assert await _count(engine, "signals") == 0

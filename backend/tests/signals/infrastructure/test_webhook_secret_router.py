"""API tests for ``GET /api/webhook-secret`` (owner decision 23; tasks.md 7.3).

The webhook secret is the one value in this system that an unauthenticated
request could turn into a forged signal, so the endpoint that returns it is
tested from four sides:

- it requires the same bearer token as every other ``/api`` route;
- it answers ``Cache-Control: no-store``;
- NO OTHER ``/api`` route, of any method, ever puts the value in a body or a
  header. The routes are read from the application's own route table, so a route
  added next month is covered without anyone remembering to list it;
- nothing in any log record, at any level, carries it, including the access log
  of a REAL uvicorn server started with uvicorn's own logging configuration.

The secret rides in the response BODY, not the URL, so the URL redaction filter
in ``shared/infrastructure/access_log.py`` is not what protects it here: what
protects it is that nothing ever logs a value it holds.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import uvicorn
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from tests.accounts.infrastructure.test_pools_router import _reserve, _snapshot
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.performance.infrastructure.test_performance_router import _trade

TOKEN = "adm1n-t0ken"
SECRET = "wh-s3cret-7d41c9e2-must-never-leak"
SECRET_PATH = "/api/webhook-secret"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """No database: this route reads the setting and nothing else."""
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as api:
        yield api


# --- the endpoint itself ----------------------------------------------------------


async def test_get_webhook_secret_requires_bearer_token(client: AsyncClient) -> None:
    missing = await client.get(SECRET_PATH)
    wrong = await client.get(SECRET_PATH, headers={"Authorization": "Bearer not-the-token"})
    basic = await client.get(SECRET_PATH, headers={"Authorization": f"Basic {TOKEN}"})

    assert [missing.status_code, wrong.status_code, basic.status_code] == [401, 401, 401]
    for refusal in (missing, wrong, basic):
        assert refusal.json() == {"detail": UNAUTHORIZED_DETAIL}
        assert SECRET not in refusal.text

    granted = await client.get(SECRET_PATH, headers=_auth())
    assert granted.status_code == 200


async def test_get_webhook_secret_returns_cache_control_no_store(client: AsyncClient) -> None:
    response = await client.get(SECRET_PATH, headers=_auth())

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert response.json() == {"secret": SECRET}


async def test_an_unconfigured_secret_is_refused_never_returned_as_an_empty_value(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", "")

    response = await client.get(SECRET_PATH, headers=_auth())

    assert response.status_code == 503
    assert "secret" not in response.json()
    assert response.json() == {"detail": "the webhook secret is not configured"}
    assert response.headers.get("cache-control") == "no-store"


async def test_the_dedicated_endpoint_is_not_a_method_other_than_get(client: AsyncClient) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await client.request(method, SECRET_PATH, headers=_auth())
        assert response.status_code == 405, method
        assert SECRET not in response.text


# --- no other route carries it ------------------------------------------------------

_SAMPLE_PATH_PARAMS = {"exchange": "bybit", "venue": "usdt-m", "ccy": "USDT"}
_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PUT", "/api/strategies/{strategy_id}/allowed-pairs"): {"pairs": ["ETHUSDT", "SOLUSDT"]},
    ("PATCH", "/api/strategies/{strategy_id}"): {"name": "renamed", "enabled": False},
    ("POST", "/api/reconciliation/bookings/{proposal_id}/reject"): {"reason": "seeded"},
}


#: Lists whose rows need a multi-table reconciliation fixture (scan, discrepancy,
#: booking proposal). They are still requested and inspected; they are only
#: allowed to answer an empty list. Every other GET must answer real data.
_MAY_BE_EMPTY = {
    ("GET", "/api/reconciliation/bookings"),
    ("GET", "/api/reconciliation/discrepancies"),
}


def _other_api_routes() -> list[tuple[str, str]]:
    """Every ``(METHOD, path template)`` under ``/api`` except the secret's own,
    taken from the application's route table.

    ``iter_route_contexts`` resolves routers that were included lazily, so the
    prefix each one was mounted under is part of the path returned.
    """
    routes = {
        (method, route.path)
        for route in iter_route_contexts(create_app().routes)
        if route.path is not None and route.path.startswith("/api") and route.methods
        for method in route.methods - {"HEAD", "OPTIONS"}
        if route.path != SECRET_PATH
    }
    return sorted(routes)


OTHER_API_ROUTES = _other_api_routes()


def test_the_route_table_walk_finds_the_routes_it_is_meant_to_cover() -> None:
    """A walk that silently found nothing would turn the parametrized test below
    into a vacuous pass."""
    assert ("GET", "/api/strategies") in OTHER_API_ROUTES
    assert ("GET", "/api/pools") in OTHER_API_ROUTES
    assert ("GET", "/api/performance/strategies/{strategy_id}") in OTHER_API_ROUTES
    assert ("POST", "/api/reconciliation/bookings/{proposal_id}/approve") in OTHER_API_ROUTES
    assert ("GET", SECRET_PATH) not in OTHER_API_ROUTES
    # The walk agrees with the schema the application publishes for itself.
    published = {
        (method.upper(), path)
        for path, operations in create_app().openapi()["paths"].items()
        if path.startswith("/api") and path != SECRET_PATH
        for method in operations
    }
    assert published <= set(OTHER_API_ROUTES)


def _concrete_path(template: str, strategy_id: UUID) -> str:
    path = template
    for name in [part[1:-1] for part in template.split("/") if part.startswith("{")]:
        if name == "strategy_id":
            value = str(strategy_id)
        else:
            # An unknown parameter still gets a request: a route added later is
            # exercised (with a value that resolves to a 404 at worst) rather
            # than skipped.
            value = _SAMPLE_PATH_PARAMS.get(name, str(uuid4()))
        path = path.replace("{" + name + "}", value)
    return path


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "template"), OTHER_API_ROUTES, ids=[f"{m} {p}" for m, p in OTHER_API_ROUTES]
)
async def test_no_other_api_response_body_contains_the_configured_secret_value(
    method: str,
    template: str,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    factory = pg_session_factory
    strategy_id = uuid4()
    await seed_strategy(factory, strategy_id=strategy_id)
    await _snapshot(factory, "bybit", "usdt-m", "USDT", total="1000", available="800")
    await _reserve(factory, "bybit", "usdt-m", "USDT", "150", strategy_id=strategy_id)
    await _trade(factory, strategy_id, datetime.now(UTC) - timedelta(hours=2))

    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session

    body = _BODIES.get((method, template))
    if body is None and method == "POST" and template == "/api/strategies":
        body = {
            "id": str(uuid4()),
            "name": "registered-by-the-secret-sweep",
            "exchange": "bybit",
            "venue": "usdt-m",
            "settlement_currency": "USDT",
            "fill_mode": "PARTIAL",
            "allowed_pairs": ["ETHUSDT"],
        }
    elif body is None and method in {"POST", "PUT", "PATCH"}:
        body = {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        # One real state change first, so the strategy has an enablement event
        # for ``.../events`` to list.
        toggled = await api.patch(
            f"/api/strategies/{strategy_id}", json={"enabled": False}, headers=_auth()
        )
        assert toggled.status_code == 200
        response = await api.request(
            method,
            _concrete_path(template, strategy_id),
            headers=_auth(),
            json=body,
        )

    # The route must have really run: an authenticated request that reached the
    # handler, never a refusal at the door and never a crash. A GET must also
    # find its data, or the sweep would be inspecting an empty body.
    assert response.status_code not in {401, 403}, f"{method} {template} was refused at the door"
    assert response.status_code < 500, f"{method} {template} crashed"
    if method == "GET":
        assert response.status_code == 200, (
            f"{method} {template} answered {response.status_code}; seed the data it needs"
        )
        if (method, template) not in _MAY_BE_EMPTY:
            assert response.text not in {"[]", "{}"}, (
                f"{method} {template} answered an empty body"
            )

    assert SECRET not in response.text, f"{method} {template} put the secret in its body"
    for name, value in response.headers.items():
        assert SECRET not in name and SECRET not in value, (
            f"{method} {template} put the secret in the {name} header"
        )


# --- no log record carries it -----------------------------------------------------------


class _Capture(logging.Handler):
    """Keeps every record it is handed, at every level."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.records: dict[int, logging.LogRecord] = {}

    def emit(self, record: logging.LogRecord) -> None:
        # Keyed by identity: a record reaches this handler once per logger it
        # was attached to, and counting it twice would prove nothing.
        self.records[id(record)] = record


def _everything_a_record_says(record: logging.LogRecord) -> str:
    """The message, its raw template and arguments, and any traceback."""
    parts = [str(record.msg), str(record.args), record.name]
    with contextlib.suppress(Exception):
        parts.append(record.getMessage())
    if record.exc_info:
        parts.append(logging.Formatter().formatException(record.exc_info))
    if record.exc_text:
        parts.append(record.exc_text)
    if record.stack_info:
        parts.append(record.stack_info)
    return "\n".join(parts)


def _all_loggers() -> list[logging.Logger]:
    known = logging.root.manager.loggerDict.values()
    return [logging.root, *[lg for lg in known if isinstance(lg, logging.Logger)]]


@contextlib.contextmanager
def _logging_restored() -> Iterator[None]:
    """Uvicorn's ``dictConfig`` rewires process-wide logging (handlers,
    ``propagate``, levels); put every logger back so no other test inherits it."""
    saved = {
        lg.name: (list(lg.handlers), list(lg.filters), lg.level, lg.propagate, lg.disabled)
        for lg in _all_loggers()
    }
    try:
        yield
    finally:
        for lg in _all_loggers():
            handlers, filters, level, propagate, disabled = saved.get(
                lg.name, ([], [], logging.NOTSET, True, False)
            )
            lg.handlers[:] = handlers
            lg.filters[:] = filters
            lg.setLevel(level)
            lg.propagate = propagate
            lg.disabled = disabled


async def test_access_log_never_records_the_secret_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A real uvicorn server, started with uvicorn's own logging configuration
    and serving the module-level ``app`` that ``uvicorn strategy_manager.main:app``
    serves, receives a real request for the secret over a real socket."""
    capture = _Capture()
    with _logging_restored():
        config = uvicorn.Config(
            "strategy_manager.main:app",
            host="127.0.0.1",
            port=0,
            lifespan="off",
            log_level="debug",
            access_log=True,
        )
        # Hook every logger that exists once uvicorn has configured logging, and
        # the root, whose level is opened so nothing is dropped for being quiet.
        logging.root.setLevel(logging.DEBUG)
        logging.root.addHandler(capture)
        for lg in _all_loggers():
            lg.addHandler(capture)

        server = uvicorn.Server(config)
        serving = asyncio.create_task(server.serve())
        try:
            for _ in range(200):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            assert server.started, "the uvicorn server did not start"
            port = server.servers[0].sockets[0].getsockname()[1]

            async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as api:
                response = await api.get(SECRET_PATH, headers=_auth())
        finally:
            server.should_exit = True
            await serving

    assert response.status_code == 200
    assert response.json() == {"secret": SECRET}

    records = list(capture.records.values())
    access_lines = [
        r.getMessage()
        for r in records
        if r.name == "uvicorn.access" and "webhook-secret" in r.getMessage()
    ]
    assert access_lines, "the request never reached the access log, so nothing was proven"

    leaked = [(r.name, r.levelname) for r in records if SECRET in _everything_a_record_says(r)]
    assert leaked == [], f"the secret reached log records from: {leaked}"

    streams = capsys.readouterr()
    assert SECRET not in streams.out
    assert SECRET not in streams.err

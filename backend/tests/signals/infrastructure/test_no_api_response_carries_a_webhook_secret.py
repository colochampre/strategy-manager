"""No ``/api`` response carries a strategy's webhook secret, except the two that
issue one (multi-user design AD6; tasks.md D.3).

A strategy's webhook secret is the one value that lets a stranger post a signal for
it, and the database keeps only its SHA-256. It is shown exactly twice: in the
answer to ``POST /api/strategies`` and in the answer to
``POST /api/strategies/{id}/webhook-secret``. This walks the application's own
route table, so a route added next month is covered without anyone remembering to
list it, and asks every route, of any method, that:

- no body or header contains the strategy's secret, the stored hash, or the global
  ``Settings.webhook_secret`` (which stays until a later PR removes it);
- no body contains the name ``webhook_secret_hash``;
- no body but those two contains the name ``webhook_secret`` either.

The ``GET /api/webhook-secret`` route that used to return the global secret is
gone; the table test below pins that it stays gone.

This module also keeps the logging helpers that ``test_credentials_logging.py``
shares.
"""

import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from fastapi.routing import iter_route_contexts
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.application.save_credential import SaveCredential
from strategy_manager.accounts.domain.exchange_credential import (
    ExchangeCredential,
    FactSource,
    KeyFacts,
)
from strategy_manager.accounts.infrastructure.capital_pool_writer import (
    SqlAlchemyCapitalPoolWriter,
)
from strategy_manager.accounts.infrastructure.credential_vault import SqlAlchemyCredentialVault
from strategy_manager.accounts.infrastructure.credentials_router import get_save_credential
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.crypto import MASTER_KEY_BYTES, EnvelopeCipher
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
from tests.accounts.fakes import (
    NOW,
    TRADING_SNAPSHOT,
    RecordingInspector,
    TickingClock,
    registry_for,
)
from tests.accounts.infrastructure.test_pools_router import _reserve, _snapshot
from tests.accounts.pool_seed import clear_discrepancies, seed_discrepancy
from tests.identity_auth import ADMIN_HEADERS, seed_admin, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.owner import secret_hash, seed_pool, seed_snapshot
from tests.performance.infrastructure.test_performance_router import _trade

#: The global setting, still present until a later PR removes it.
GLOBAL_SECRET = "wh-s3cret-7d41c9e2-must-never-leak"
#: The seeded strategy's own secret, of which only the hash is stored.
STRATEGY_SECRET = "strategy-s3cret-91ab-must-never-leak"
STORED_HASH = secret_hash(STRATEGY_SECRET)
REMOVED_PATH = "/api/webhook-secret"
CREATE = ("POST", "/api/strategies")
REGENERATE = ("POST", "/api/strategies/{strategy_id}/webhook-secret")
#: The only two routes whose answer carries a (new) secret.
ISSUING = {CREATE, REGENERATE}


@pytest.fixture(autouse=True)
def _configure_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)
    monkeypatch.setattr(get_settings(), "webhook_secret", GLOBAL_SECRET)


_SAMPLE_PATH_PARAMS = {
    "exchange": "bybit",
    "venue": "usdt-m",
    "ccy": "USDT",
    "settlement_currency": "USDT",
}


class _SweepPairCatalog:
    """A fake venue catalogue: a non-empty answer and no network. It lists the
    pairs the sweep's own POST and PUT bodies use, so those two requests reach
    their real 201 and 200 instead of an unlisted-pair refusal."""

    async def available_pairs(self, pool: tuple[str, str, str]) -> frozenset[str]:
        return frozenset({"STXUSDT", "ETHUSDT", "SOLUSDT"})


_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("PUT", "/api/strategies/{strategy_id}/allowed-pairs"): {"pairs": ["ETHUSDT", "SOLUSDT"]},
    ("PATCH", "/api/strategies/{strategy_id}"): {"name": "renamed", "enabled": False},
    # A REAL body, so the route answers 200 with facts and not an empty refusal (W2).
    ("PUT", "/api/credentials/{exchange}"): {
        "api_key": "SWEEP-FAKE-KEY-abcd",
        "api_secret": "SWEEP-FAKE-SECRET-wxyz",
    },
    ("PATCH", "/api/subscriptions/{subscription_id}"): {"allocation_percent": "40"},
}


#: Write routes whose handler reads no body at all: their answers are their own
#: named refusals or successes, whatever the request carries.
_NO_BODY = {
    ("DELETE", "/api/credentials/{exchange}"),
    ("DELETE", "/api/strategies/{strategy_id}"),
    ("POST", "/api/strategies/{strategy_id}/archive"),
    REGENERATE,
    ("POST", "/api/subscriptions/{subscription_id}/leave"),
}


def _other_api_routes() -> list[tuple[str, str]]:
    """Every ``(METHOD, path template)`` under ``/api``, taken from the
    application's route table.

    ``iter_route_contexts`` resolves routers that were included lazily, so the
    prefix each one was mounted under is part of the path returned.
    """
    routes = {
        (method, route.path)
        for route in iter_route_contexts(create_app().routes)
        if route.path is not None and route.path.startswith("/api") and route.methods
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    return sorted(routes)


API_ROUTES = _other_api_routes()


def test_the_route_table_walk_finds_the_routes_it_is_meant_to_cover() -> None:
    """A walk that silently found nothing would turn the parametrized test below
    into a vacuous pass."""
    assert ("GET", "/api/strategies") in API_ROUTES
    assert ("GET", "/api/pools") in API_ROUTES
    assert ("GET", "/api/performance/strategies/{strategy_id}") in API_ROUTES
    assert (
        "GET",
        "/api/performance/strategies/{strategy_id}/trades/{allocation_id}/fills",
    ) in API_ROUTES
    # The confirmed-discrepancies read joins the sweep; the three booking
    # routes left it (owner decision 66 Q1, cd.1.33).
    assert ("GET", "/api/reconciliation/confirmed") in API_ROUTES
    assert ("GET", "/api/reconciliation/discrepancies") in API_ROUTES
    assert not [route for route in API_ROUTES if "/reconciliation/bookings" in route[1]]
    assert ("GET", "/api/webhook-origin") in API_ROUTES
    assert ("GET", "/api/strategies/{strategy_id}/share-preview") in API_ROUTES
    # The two routes that issue a secret are walked, and the one that used to
    # reveal the global secret is gone for every method.
    assert CREATE in API_ROUTES
    assert REGENERATE in API_ROUTES
    assert not [route for route in API_ROUTES if route[1] == REMOVED_PATH]
    # The walk agrees with the schema the application publishes for itself.
    published = {
        (method.upper(), path)
        for path, operations in create_app().openapi()["paths"].items()
        if path.startswith("/api")
        for method in operations
    }
    assert published <= set(API_ROUTES)


def _concrete_path(
    template: str, strategy_id: UUID, allocation_id: UUID, subscription_id: UUID
) -> str:
    path = template
    for name in [part[1:-1] for part in template.split("/") if part.startswith("{")]:
        if name == "strategy_id":
            value = str(strategy_id)
        elif name == "subscription_id":
            # The signed-in admin's own subscription, so leave and patch answer
            # the row rather than a 404 (AD8).
            value = str(subscription_id)
        elif name == "allocation_id":
            # The allocation of the trade the sweep seeds, so the fills route finds
            # the data it needs (a random id would be its 404).
            value = str(allocation_id)
        else:
            # An unknown parameter still gets a request: a route added later is
            # exercised (with a value that resolves to a 404 at worst) rather
            # than skipped.
            value = _SAMPLE_PATH_PARAMS.get(name, str(uuid4()))
        path = path.replace("{" + name + "}", value)
    return path


@pytest.mark.integration
@pytest.mark.parametrize(
    ("method", "template"), API_ROUTES, ids=[f"{m} {p}" for m, p in API_ROUTES]
)
async def test_no_api_response_carries_a_secret_or_a_hash_except_the_two_that_issue_one(
    method: str,
    template: str,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    factory = pg_session_factory
    strategy_id = uuid4()
    # The strategy is the signed-in admin's own, so the regenerate route reaches its
    # real 200 and not the 404 a stranger's strategy answers.
    async with factory() as session:
        admin = await seed_admin(session)
        await session.commit()
    await seed_strategy(factory, strategy_id=strategy_id, author_id=admin)
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE strategies SET webhook_secret_hash = :hash, "
                "webhook_secret_last4 = :last4 WHERE id = :id"
            ),
            {"hash": STORED_HASH, "last4": STRATEGY_SECRET[-4:], "id": strategy_id},
        )
        # The pool routes answer the signed-in admin's pools, and the share preview
        # reads the strategy author's (AD8): both users hold a synced Bybit pool.
        await seed_pool(session, ("bybit", "usdt-m", "USDT"), user_id=admin)
        await seed_snapshot(
            session,
            ("bybit", "usdt-m", "USDT"),
            total=Decimal("1000"),
            available=Decimal("800"),
            observed_at=datetime.now(UTC),
        )
        await session.commit()
    # The admin's subscription to the strategy, so the subscriptions list is not
    # empty and leave and patch reach a real row.
    subscription_id = uuid4()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, strategy_id, pool_id, allocation_percent) "
                "SELECT :id, :user, :strategy, id, 30 FROM capital_pools "
                "WHERE user_id = :user AND exchange = 'bybit' AND venue = 'usdt-m' "
                "AND settlement_currency = 'USDT'"
            ),
            {"id": subscription_id, "user": admin, "strategy": strategy_id},
        )
        await session.commit()
    await _snapshot(factory, "bybit", "usdt-m", "USDT", total="1000", available="800")
    await _reserve(factory, "bybit", "usdt-m", "USDT", "150", strategy_id=strategy_id)
    # The fills route answers the signed-in admin's own operation (AD8).
    allocation_id = await _trade(
        factory, strategy_id, datetime.now(UTC) - timedelta(hours=2), user_id=admin
    )
    # One open discrepancy, so the list's row serializer is inspected too (W3).
    await clear_discrepancies(factory)
    await seed_discrepancy(factory, symbol="STXUSDT")
    cipher = EnvelopeCipher(bytes(MASTER_KEY_BYTES))
    async with factory() as session:
        # An active key, so ``GET /api/credentials`` answers a STORED entry and
        # not only the empty ones an enabled pool produces. The admin's own key:
        # the listing answers only the signed-in user's keys (AD8).
        await session.execute(text("TRUNCATE exchange_credentials CASCADE"))
        await SqlAlchemyCredentialVault(session, cipher, TickingClock()).store(
            admin,
            ExchangeCredential(
                exchange="bybit",
                label="default",
                api_key="SEEDED-FAKE-KEY-9876",
                api_secret="SEEDED-FAKE-SECRET",
            ),
            KeyFacts(
                trade_capable=True,
                trade_capability_source=FactSource.VERIFIED,
                trade_confirmed_at=None,
                withdraw_check=FactSource.VERIFIED,
                withdraw_confirmed_at=None,
                validated_at=NOW,
                internal_transfer=False,
            ),
        )
        await session.commit()

    app = create_app()

    async def _save_credential(
        session: Annotated[AsyncSession, Depends(shared_db.get_session)],
    ) -> SaveCredential:
        """The real use case over the real vault, with a FAKE venue: a sweep
        request must never reach a live exchange."""
        clock = TickingClock()
        return SaveCredential(
            registry_for(RecordingInspector(TRADING_SNAPSHOT)),
            SqlAlchemyCredentialVault(session, cipher, clock),
            SqlAlchemyCapitalPoolWriter(session),
            session,
            clock,
        )

    app.dependency_overrides[get_save_credential] = _save_credential
    # No network from the suite; the available-pairs body must be non-empty to be inspected.
    app.dependency_overrides[get_pair_catalog] = _SweepPairCatalog

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session

    body = _BODIES.get((method, template))
    if body is None and (method, template) == CREATE:
        body = {
            "id": str(uuid4()),
            "name": "registered-by-the-secret-sweep",
            "exchange": "bybit",
            "venue": "usdt-m",
            "settlement_currency": "USDT",
            "fill_mode": "PARTIAL",
            "allowed_pairs": ["ETHUSDT"],
        }
    elif body is None and method == "POST" and template == "/api/subscriptions":
        body = {"strategy_id": str(strategy_id), "allocation_percent": "30"}
    elif body is None and method != "GET" and (method, template) not in _NO_BODY:
        # A write route added later must be given a real body in ``_BODIES``; a
        # blind ``{}`` would earn a 422 and the sweep would inspect nothing (W2).
        pytest.fail(f"{method} {template} is a write route with no body in _BODIES or _NO_BODY")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        # One real state change first, so the strategy has an enablement event
        # for ``.../events`` to list.
        toggled = await api.patch(
            f"/api/strategies/{strategy_id}", json={"enabled": False}, headers=ADMIN_HEADERS
        )
        assert toggled.status_code == 200
        response = await api.request(
            method,
            _concrete_path(template, strategy_id, allocation_id, subscription_id),
            headers=ADMIN_HEADERS,
            json=body,
        )

    # The route must have really run: an authenticated request that reached the
    # handler, never a refusal at the door and never a crash. A GET must also
    # find its data, or the sweep would be inspecting an empty body.
    assert response.status_code not in {401, 403}, f"{method} {template} was refused at the door"
    assert response.status_code < 500, f"{method} {template} crashed"
    if method != "GET":
        # FastAPI's validation refusal means the body never reached the handler,
        # so the sweep would be inspecting a trivial 4xx answer (W2).
        assert response.status_code != 422, (
            f"{method} {template} answered 422: the sweep's body did not reach the handler"
        )
    if method == "GET":
        assert response.status_code == 200, (
            f"{method} {template} answered {response.status_code}; seed the data it needs"
        )
        assert response.text not in {"[]", "{}"}, f"{method} {template} answered an empty body"

    if (method, template) == ("PUT", "/api/credentials/{exchange}"):
        assert response.status_code == 200, "the sweep's credential body must really be saved"
        assert response.json()["last4"] == "abcd"
    if (method, template) == ("DELETE", "/api/credentials/{exchange}"):
        # The DELETE carries no body. It must have really run its precondition:
        # the seed holds a live reservation and a trade on bybit, so the answer is
        # the 409 that names them, not a 404 or a success.
        assert response.status_code == 409, "the sweep's DELETE must reach the pool check"
        assert response.json()["outcome"] == "EXCHANGE_NOT_FLAT"
    if (method, template) == ("GET", "/api/reconciliation/discrepancies"):
        assert "STXUSDT" in response.text, "the seeded discrepancy must be served"
    if (method, template) == ("GET", "/api/credentials"):
        stored = [entry for entry in response.json() if entry["status"] == "STORED"]
        assert [entry["last4"] for entry in stored] == ["9876"]
    if (method, template) in {("GET", "/api/strategies"), ("GET", "/api/strategies/{strategy_id}")}:
        # The one place a character of the strategy's secret may leave: its last four,
        # as the panel masks it, and nothing longer.
        payload = response.json()
        rows = payload if isinstance(payload, list) else [payload]
        assert [row["secret_last4"] for row in rows] == [STRATEGY_SECRET[-4:]]
        assert STRATEGY_SECRET[-5:] not in response.text

    # Never a value already held, on any route.
    forbidden = (GLOBAL_SECRET, STRATEGY_SECRET, STORED_HASH, "webhook_secret_hash")
    for value in forbidden:
        assert value not in response.text, f"{method} {template} put {value[:8]}... in its body"
        for name, header in response.headers.items():
            assert value not in name and value not in header, (
                f"{method} {template} put {value[:8]}... in the {name} header"
            )

    if (method, template) in ISSUING:
        # The issuing routes carry a NEW secret under its own name, once, and not
        # its hash. The create and the regenerate really ran, or the sweep would
        # inspect a refusal instead of an issuing answer.
        assert response.status_code in {200, 201}, f"{method} {template} issued nothing"
        issued = response.json()["webhook_secret"]
        assert issued not in {GLOBAL_SECRET, STRATEGY_SECRET}
        assert secret_hash(issued) not in response.text
    else:
        assert "webhook_secret" not in response.text, (
            f"{method} {template} is not an issuing route but names a webhook secret"
        )


# --- helpers shared with the logging tests ----------------------------------------------


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

"""API tests for the strategy-lifecycle endpoints added in unit 2e:
``PUT /strategies/{id}/allowed-pairs``, ``GET /strategies/{id}/events``, the
``include_archived`` list filter, ``POST /strategies``' new `allowed_pairs`
requirement, and the `StrategyView` fields those endpoints and the
existing CRUD routes now carry (design.md § 14 "Endpoints"; spec:
strategy-lifecycle; tasks.md 2e.3).

Mirrors ``tests/reconciliation/infrastructure/test_router.py``'s own
pattern: a bare ``FastAPI()`` app with only this router mounted, the admin
token configured explicitly (not inherited from the environment), and
``get_session`` overridden to a real Postgres session from
``pg_session_factory`` -- the router reads real rows back through the real
repository/adapters, never a fake.

Archiving a strategy is done here by a direct SQL ``UPDATE`` (no
``ArchiveStrategy`` use case exists yet -- that ships in PR 5): this unit
only builds the LISTING filter and the detail endpoint's unconditional
load, not the archive action itself (binding instruction: no
archived-strategy refusals in this unit).
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.performance.infrastructure.performance_router import (
    router as performance_router,
)
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.delete_strategy import DeleteStrategy
from strategy_manager.strategies.application.ports import PoolKey, StrategyHistory
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
)
from strategy_manager.strategies.infrastructure.enablement_log import SqlAlchemyEnablementLog
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import SqlAlchemyStrategyRepository
from strategy_manager.strategies.infrastructure.router import (
    SessionDep,
    get_delete_strategy,
)
from strategy_manager.strategies.infrastructure.router import router as strategies_router

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _Catalog:
    """A fake ``PairCatalogPort``: it answers ``available`` for every pool and
    records which pools it was asked about. The default list holds every symbol
    the older tests here register or add, so they run unchanged."""

    def __init__(
        self,
        available: frozenset[str] = frozenset({"ETHUSDT", "SOLUSDT"}),
        failure: Exception | None = None,
    ) -> None:
        self.available = available
        self.failure = failure
        self.asked: list[PoolKey] = []
        # Runs while the venue "answers": how a test plays another request that
        # commits during the venue read.
        self.during_read: Callable[[], Awaitable[None]] | None = None

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.asked.append(pool)
        if self.during_read is not None:
            await self.during_read()
        if self.failure is not None:
            raise self.failure
        return self.available


def _app(catalog: _Catalog | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(strategies_router)
    fake = catalog or _Catalog()
    app.dependency_overrides[get_pair_catalog] = lambda: fake
    return app


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:  # type: ignore[misc]
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    yield


async def _authenticated_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
    catalog: _Catalog | None = None,
    raise_app_exceptions: bool = True,
) -> AsyncIterator[AsyncClient]:
    from strategy_manager.shared import db as shared_db

    # ``strategy_enablement_events`` (migration 0024) has no ORM-level FK to
    # ``strategies`` -- following the SAME deliberate convention
    # ``BookingProposalRow`` documents for itself (this test file's own
    # docstring precedent) -- so ``pg_engine``'s
    # ``TRUNCATE strategies, capital_pools ... CASCADE`` never reaches it,
    # and a prior test's events would otherwise leak into this one's.
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE strategy_enablement_events"))
        await session.commit()

    app = _app(catalog)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async for api in _authenticated_client(pg_session_factory):
        yield api


async def _register(client: AsyncClient, **overrides: Any) -> UUID:
    strategy_id: UUID = overrides.pop("id", uuid4())
    body: dict[str, Any] = {
        "id": str(strategy_id),
        "name": overrides.pop("name", f"strategy-{strategy_id}"),
        "exchange": "pionex",
        "venue": "spot",
        "settlement_currency": "USDT",
        "fill_mode": "PARTIAL",
        "allowed_pairs": overrides.pop("allowed_pairs", ["ETHUSDT"]),
    }
    body.update(overrides)
    response = await client.post("/strategies", json=body, headers=_auth())
    assert response.status_code == 201, response.text
    return strategy_id


async def _archive_directly(
    pg_session_factory: async_sessionmaker[AsyncSession], strategy_id: UUID
) -> None:
    """No ``ArchiveStrategy`` use case exists yet (PR 5) -- this unit only
    needs an archived row to exist to prove the LIST filter and detail
    endpoint behave correctly around it."""
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET archived_at = now() WHERE id = :id"),
            {"id": strategy_id},
        )
        await session.commit()


# --------------------------------------------------------------------------
# 2e.3 -- list excludes archived by default, include_archived shows them,
# detail always loads regardless
# --------------------------------------------------------------------------


async def test_get_strategies_excludes_archived_by_default(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    visible_id = await _register(client, name="visible")
    archived_id = await _register(client, name="to-archive")
    await _archive_directly(pg_session_factory, archived_id)

    response = await client.get("/strategies", headers=_auth())

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(visible_id) in ids
    assert str(archived_id) not in ids


async def test_get_strategies_include_archived_true_shows_archived(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    archived_id = await _register(client, name="to-archive")
    await _archive_directly(pg_session_factory, archived_id)

    response = await client.get("/strategies?include_archived=true", headers=_auth())

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(archived_id) in ids


async def test_get_strategy_detail_by_id_always_loads_archived(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    archived_id = await _register(client, name="to-archive")
    await _archive_directly(pg_session_factory, archived_id)

    response = await client.get(f"/strategies/{archived_id}", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body["archived_at"] is not None


# --------------------------------------------------------------------------
# 2e.3 / binding 3 -- PUT allowed-pairs: normalization, duplicates, refusals
# --------------------------------------------------------------------------


async def test_put_allowed_pairs_endpoint(client: AsyncClient) -> None:
    """Spelled DIFFERENTLY from how it is stored and returned: PUT
    ``solusdt.p`` (TradingView's own casing/marker), read back as
    ``SOLUSDT`` -- proving the endpoint normalizes rather than echoing raw
    input."""
    strategy_id = await _register(client, allowed_pairs=["ETHUSDT"])

    response = await client.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["solusdt.p"]},
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json()["allowed_pairs"] == ["SOLUSDT"]


async def test_put_allowed_pairs_collapses_duplicates_after_normalization(
    client: AsyncClient,
) -> None:
    strategy_id = await _register(client)

    response = await client.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["SOLUSDT.P", "SOLUSDT_PERP", "solusdt"]},
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json()["allowed_pairs"] == ["SOLUSDT"]


async def test_put_allowed_pairs_empty_list_refused_422(client: AsyncClient) -> None:
    strategy_id = await _register(client)

    response = await client.put(
        f"/strategies/{strategy_id}/allowed-pairs", json={"pairs": []}, headers=_auth()
    )

    assert response.status_code == 422


async def test_put_allowed_pairs_entries_normalizing_to_empty_refused_422(
    client: AsyncClient,
) -> None:
    strategy_id = await _register(client)

    response = await client.put(
        f"/strategies/{strategy_id}/allowed-pairs", json={"pairs": [".P"]}, headers=_auth()
    )

    assert response.status_code == 422


async def test_put_allowed_pairs_unknown_strategy_404(client: AsyncClient) -> None:
    response = await client.put(
        f"/strategies/{uuid4()}/allowed-pairs", json={"pairs": ["ETHUSDT"]}, headers=_auth()
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------
# 2e.3 -- POST requires at least one pair
# --------------------------------------------------------------------------


async def test_post_strategies_requires_min_one_pair_422(client: AsyncClient) -> None:
    body = {
        "id": str(uuid4()),
        "name": "no-pairs",
        "exchange": "pionex",
        "venue": "spot",
        "settlement_currency": "USDT",
        "fill_mode": "PARTIAL",
        "allowed_pairs": [],
    }

    response = await client.post("/strategies", json=body, headers=_auth())

    assert response.status_code == 422


# --------------------------------------------------------------------------
# 2e.3 -- GET events
# --------------------------------------------------------------------------


async def test_get_strategy_events_endpoint(client: AsyncClient) -> None:
    strategy_id = await _register(client)

    await client.patch(f"/strategies/{strategy_id}", json={"enabled": True}, headers=_auth())
    await client.patch(f"/strategies/{strategy_id}", json={"enabled": False}, headers=_auth())

    response = await client.get(f"/strategies/{strategy_id}/events", headers=_auth())

    assert response.status_code == 200
    events = response.json()
    assert len(events) == 2
    assert events[0]["enabled"] is True
    assert events[0]["origin"] == "OBSERVED"
    assert events[1]["enabled"] is False


async def test_get_strategy_events_unknown_strategy_404(client: AsyncClient) -> None:
    response = await client.get(f"/strategies/{uuid4()}/events", headers=_auth())

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Binding 5 -- StrategyView carries uptime, on both list and detail
# --------------------------------------------------------------------------


async def test_strategy_view_uptime_reflects_events_on_detail_and_list(
    client: AsyncClient,
) -> None:
    strategy_id = await _register(client)

    await client.patch(f"/strategies/{strategy_id}", json={"enabled": True}, headers=_auth())
    await client.patch(f"/strategies/{strategy_id}", json={"enabled": False}, headers=_auth())

    detail = await client.get(f"/strategies/{strategy_id}", headers=_auth())
    assert detail.status_code == 200
    assert detail.json()["uptime"]["seconds"] >= 0
    assert detail.json()["uptime"]["baseline"] is False

    listing = await client.get("/strategies", headers=_auth())
    assert listing.status_code == 200
    by_id = {row["id"]: row for row in listing.json()}
    assert by_id[str(strategy_id)]["uptime"]["seconds"] == detail.json()["uptime"]["seconds"]


# --------------------------------------------------------------------------
# 2c.14 -- POST /{id}/archive, and archived-strategy refusals at the HTTP
# layer (design.md § 8, § 14 "Endpoints")
# --------------------------------------------------------------------------


async def test_archive_endpoint_succeeds_on_disabled_flat_strategy(client: AsyncClient) -> None:
    """A freshly registered strategy is disabled by construction (F8) --
    archiving it right away needs no PATCH first."""
    strategy_id = await _register(client)

    response = await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())

    assert response.status_code == 200
    assert response.json()["archived_at"] is not None


async def test_archive_endpoint_is_idempotent_same_archived_at(client: AsyncClient) -> None:
    strategy_id = await _register(client)

    first = await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())
    second = await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["archived_at"] == second.json()["archived_at"]


async def test_archive_endpoint_refuses_enabled_strategy_409_still_enabled(
    client: AsyncClient,
) -> None:
    strategy_id = await _register(client)
    await client.patch(f"/strategies/{strategy_id}", json={"enabled": True}, headers=_auth())

    response = await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STILL_ENABLED"


async def test_archive_endpoint_unknown_strategy_404(client: AsyncClient) -> None:
    response = await client.post(f"/strategies/{uuid4()}/archive", headers=_auth())

    assert response.status_code == 404


async def test_archive_endpoint_refuses_open_position_409_names_symbols(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """A lightweight, router-level check that the 409 ``OPEN_POSITION`` body
    is wired through with the structured fields design.md specifies --
    ``test_archive_strategy_integration.py`` already covers the exposure
    logic itself in depth; this only proves the endpoint doesn't lose it in
    translation. Seeds a live PENDING reservation directly by SQL, which is
    enough exposure to refuse without needing a full ledger fill."""
    strategy_id = await _register(client)
    signal_id = uuid4()
    reservation_id = uuid4()
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, "
                "action, contracts, position_size, price, symbol, signal_type) "
                "VALUES (:id, :strategy_id, :key, '{}'::jsonb, 'buy', 1, 1, 1, 'SEED', "
                ":signal_type)"
            ),
            {
                "id": signal_id,
                "strategy_id": strategy_id,
                "key": f"k-{signal_id}",
                "signal_type": str(strategy_id),
            },
        )
        await session.execute(
            text(
                "INSERT INTO reservations (id, strategy_id, signal_id, exchange, venue, "
                "settlement_currency, amount, status, expires_at) "
                "VALUES (:id, :strategy_id, :signal_id, 'pionex', 'spot', 'USDT', 100, "
                "'PENDING', now() + interval '30 seconds')"
            ),
            {"id": reservation_id, "strategy_id": strategy_id, "signal_id": signal_id},
        )
        await session.commit()

    response = await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())

    assert response.status_code == 409
    body = response.json()["detail"]
    assert body["error"] == "OPEN_POSITION"
    assert body["live_reservations"] == [str(reservation_id)]


async def test_archived_strategy_patch_refused_409_at_http_layer(client: AsyncClient) -> None:
    strategy_id = await _register(client)
    await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())

    response = await client.patch(
        f"/strategies/{strategy_id}", json={"name": "renamed"}, headers=_auth()
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRATEGY_ARCHIVED"


async def test_archived_strategy_pairs_put_refused_409_at_http_layer(client: AsyncClient) -> None:
    strategy_id = await _register(client)
    await client.post(f"/strategies/{strategy_id}/archive", headers=_auth())

    response = await client.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["ETHUSDT"]},
        headers=_auth(),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STRATEGY_ARCHIVED"


# --------------------------------------------------------------------------
# 9vc.7 -- unlisted-pair refusals over HTTP (decisions 40 and 41, design
# addendum § E). The catalogue is a fake; nothing reaches a venue.
#
# Spelling: the fake venue lists ``STXUSDT``; POST sends ``STXUSDT.P``; PUT sends
# ``STXUSDT_PERP``; the stored and returned form is ``STXUSDT``.
#
# The client does NOT re-raise application exceptions: an unmapped domain error
# is a 500 the test sees as ``assert 500 == 422``, not as a raised exception.
# --------------------------------------------------------------------------


@pytest.fixture
def catalog() -> _Catalog:
    return _Catalog()


@pytest.fixture
async def api(
    pg_session_factory: async_sessionmaker[AsyncSession], catalog: _Catalog
) -> AsyncIterator[AsyncClient]:
    async for client in _authenticated_client(
        pg_session_factory, catalog, raise_app_exceptions=False
    ):
        yield client


def _post_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(uuid4()),
        "name": f"strategy-{uuid4()}",
        "exchange": "pionex",
        "venue": "spot",
        "settlement_currency": "USDT",
        "fill_mode": "PARTIAL",
        "allowed_pairs": ["ETHUSDT"],
    }
    body.update(overrides)
    return body


async def _row_count(api: AsyncClient, strategy_id: str) -> int:
    response = await api.get(f"/strategies/{strategy_id}", headers=_auth())
    return 1 if response.status_code == 200 else 0


async def test_post_unknown_pairs_422_structured_and_names_the_symbols(
    api: AsyncClient, catalog: _Catalog
) -> None:
    catalog.available = frozenset({"STXUSDT"})
    body = _post_body(allowed_pairs=["STXUSDT.P", "YPF"])

    response = await api.post("/strategies", json=body, headers=_auth())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "UNKNOWN_PAIRS"
    assert detail["unknown"] == ["YPF"]
    assert isinstance(detail["message"], str)
    assert "YPF" in detail["message"]
    assert set(detail) == {"error", "message", "unknown"}
    assert await _row_count(api, body["id"]) == 0


async def test_put_unknown_pairs_422_names_only_the_added_symbols(
    api: AsyncClient, catalog: _Catalog
) -> None:
    """``ETHUSDT`` is stored and no longer listed: it is kept, so it is not named.
    ``YPF`` is the only addition the venue does not list."""
    strategy_id = await _register(api, allowed_pairs=["ETHUSDT"])
    catalog.available = frozenset({"SOLUSDT"})

    response = await api.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["ETHUSDT", "SOLUSDT_PERP", "ypf.p"]},
        headers=_auth(),
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "UNKNOWN_PAIRS"
    assert detail["unknown"] == ["YPF"]
    assert set(detail) == {"error", "message", "unknown"}
    stored = await api.get(f"/strategies/{strategy_id}", headers=_auth())
    assert stored.json()["allowed_pairs"] == ["ETHUSDT"]


async def test_put_keeping_a_delisted_stored_pair_200(api: AsyncClient, catalog: _Catalog) -> None:
    strategy_id = await _register(api, allowed_pairs=["ETHUSDT"])
    catalog.available = frozenset({"SOLUSDT"})  # ETHUSDT, stored, is delisted

    response = await api.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["ETHUSDT", "SOLUSDT_PERP"]},
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json()["allowed_pairs"] == ["ETHUSDT", "SOLUSDT"]


async def test_post_unreadable_catalogue_502_pair_catalogue_unavailable_and_no_row(
    api: AsyncClient, catalog: _Catalog
) -> None:
    catalog.failure = PairCatalogUnavailable("venue down")
    body = _post_body()

    response = await api.post("/strategies", json=body, headers=_auth())

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["error"] == "PAIR_CATALOGUE_UNAVAILABLE"
    assert isinstance(detail["message"], str)
    assert set(detail) == {"error", "message"}
    assert await _row_count(api, body["id"]) == 0


async def test_post_unserved_pool_422_pair_catalogue_not_served(
    api: AsyncClient, catalog: _Catalog
) -> None:
    catalog.failure = PairCatalogNotServed("no source")
    body = _post_body()

    response = await api.post("/strategies", json=body, headers=_auth())

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["error"] == "PAIR_CATALOGUE_NOT_SERVED"
    assert set(detail) == {"error", "message"}
    assert await _row_count(api, body["id"]) == 0


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    [
        (PairCatalogUnavailable("venue down"), 502, "PAIR_CATALOGUE_UNAVAILABLE"),
        (PairCatalogNotServed("no source"), 422, "PAIR_CATALOGUE_NOT_SERVED"),
    ],
)
async def test_put_unreadable_or_unserved_catalogue_refuses_and_keeps_the_stored_list(
    api: AsyncClient, catalog: _Catalog, failure: Exception, status: int, code: str
) -> None:
    strategy_id = await _register(api, allowed_pairs=["ETHUSDT"])
    catalog.failure = failure

    response = await api.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["ETHUSDT", "SOLUSDT"]},
        headers=_auth(),
    )

    assert response.status_code == status
    assert response.json()["detail"]["error"] == code
    stored = await api.get(f"/strategies/{strategy_id}", headers=_auth())
    assert stored.json()["allowed_pairs"] == ["ETHUSDT"]


async def test_put_pairs_changed_409(
    api: AsyncClient,
    catalog: _Catalog,
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Stored ``{ETHUSDT, SOLUSDT}``; the request adds ``STXUSDT``. While the venue
    "answers", another request removes ``SOLUSDT``: re-adding it would store a pair
    nobody checked."""
    strategy_id = await _register(api, allowed_pairs=["ETHUSDT", "SOLUSDT"])
    catalog.available = frozenset({"STXUSDT"})

    async def another_request_removes_solusdt() -> None:
        async with pg_session_factory() as session:
            await session.execute(
                text("UPDATE strategies SET allowed_pairs = ARRAY['ETHUSDT'] WHERE id = :id"),
                {"id": strategy_id},
            )
            await session.commit()

    catalog.during_read = another_request_removes_solusdt

    response = await api.put(
        f"/strategies/{strategy_id}/allowed-pairs",
        json={"pairs": ["ETHUSDT", "SOLUSDT", "STXUSDT_PERP"]},
        headers=_auth(),
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "PAIRS_CHANGED"
    assert set(detail) == {"error", "message"}
    stored = await api.get(f"/strategies/{strategy_id}", headers=_auth())
    assert stored.json()["allowed_pairs"] == ["ETHUSDT"]


async def test_existing_refusals_keep_their_status_and_shape(
    api: AsyncClient, catalog: _Catalog
) -> None:
    strategy_id = await _register(api, name="kept")

    unknown = await api.put(
        f"/strategies/{uuid4()}/allowed-pairs", json={"pairs": ["ETHUSDT"]}, headers=_auth()
    )
    assert unknown.status_code == 404
    assert isinstance(unknown.json()["detail"], str)

    duplicate = await api.post(
        "/strategies", json=_post_body(id=str(strategy_id), name="other"), headers=_auth()
    )
    assert duplicate.status_code == 409
    assert "already registered" in duplicate.json()["detail"]

    empty = await api.put(
        f"/strategies/{strategy_id}/allowed-pairs", json={"pairs": [".P"]}, headers=_auth()
    )
    assert empty.status_code == 422
    assert isinstance(empty.json()["detail"], str)

    no_pool = await api.post(
        "/strategies", json=_post_body(venue="usdt-m"), headers=_auth()
    )  # pionex/usdt-m/USDT is not a seeded pool
    assert no_pool.status_code == 422
    assert "no enabled capital pool" in no_pool.json()["detail"]

    await api.post(f"/strategies/{strategy_id}/archive", headers=_auth())
    archived = await api.put(
        f"/strategies/{strategy_id}/allowed-pairs", json={"pairs": ["ETHUSDT"]}, headers=_auth()
    )
    assert archived.status_code == 409
    assert archived.json()["detail"]["error"] == "STRATEGY_ARCHIVED"

    # None of the refusals above reached the venue (the catalogue only answered
    # the one ``_register`` that built the strategy).
    assert catalog.asked == [("pionex", "spot", "USDT")]


async def test_a_listed_pair_sent_as_tradingview_spells_it_is_stored_as_the_market_key(
    api: AsyncClient, catalog: _Catalog
) -> None:
    catalog.available = frozenset({"STXUSDT"})

    response = await api.post(
        "/strategies", json=_post_body(allowed_pairs=["STXUSDT.P"]), headers=_auth()
    )

    assert response.status_code == 201
    assert response.json()["allowed_pairs"] == ["STXUSDT"]
    assert catalog.asked == [("pionex", "spot", "USDT")]


# --------------------------------------------------------------------------
# 9xd.1 -- DELETE /strategies/{id} (decision 42, design addendum 9x, § F).
#
# The ORM schema is enough here: the route MAPS what 9xc proved on ``head``. The
# ORM does carry the foreign key on ``reservations.strategy_id``, which is what
# the database-refusal tests use for a real aborted transaction (named by the ORM
# ``reservations_strategy_id_fkey``, not the migration's ``fk_reservations_strategy``); the other
# refusals are decided by the counts.
#
# Spelling: the fake venue lists ``STXUSDT`` (the strategy's allowed pair); the
# seeded signal is ``STXUSDT.P`` as the alert sends it.
#
# The client does NOT re-raise application exceptions: an unmapped domain error
# is a 500 the test sees as ``assert 500 == 409``, not as a raised exception.
# --------------------------------------------------------------------------

_HISTORY_KEYS = {
    "signals",
    "reservations",
    "execution_attempts",
    "ledger_entries",
    "booking_proposals",
    "enablement_events",
}


def _history_body(**counts: int) -> dict[str, int]:
    return {key: counts.get(key, 0) for key in sorted(_HISTORY_KEYS)}


class _NoHistory:
    """A ``StrategyHistoryPort`` that always answers zeros: the count that
    "missed" the row the database then refuses."""

    async def history(self, strategy_id: UUID) -> StrategyHistory:
        return StrategyHistory(
            signals=0,
            reservations=0,
            execution_attempts=0,
            ledger_entries=0,
            booking_proposals=0,
            enablement_events=0,
        )


async def _delete_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
    catalog: _Catalog,
    shared_session: AsyncSession | None = None,
    miscounting: bool = False,
) -> AsyncIterator[AsyncClient]:
    """The strategies AND performance routers over ASGI on real PostgreSQL.

    ``shared_session`` makes every request use ONE session that no request
    closes, so a transaction a request leaves aborted is still there for the next
    one; the default (a session per request) would hide a missing rollback.
    ``miscounting`` replaces the history with zeros, so the database refuses.
    """
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE strategy_enablement_events"))
        await session.commit()

    app = _app(catalog)
    app.include_router(performance_router)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        if shared_session is not None:
            yield shared_session
            return
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session

    if miscounting:

        def _override_delete(session: SessionDep) -> DeleteStrategy:
            return DeleteStrategy(
                repository=SqlAlchemyStrategyRepository(session),
                pool_lock=PoolLockAdapter(session),
                history=_NoHistory(),
                enablement_log=SqlAlchemyEnablementLog(session),
                clock=SystemClock(),
                commit=session,
            )

        app.dependency_overrides[get_delete_strategy] = _override_delete

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


@pytest.fixture
async def deleting(
    pg_session_factory: async_sessionmaker[AsyncSession], catalog: _Catalog
) -> AsyncIterator[AsyncClient]:
    catalog.available = frozenset({"STXUSDT"})
    async for api in _delete_client(pg_session_factory, catalog):
        yield api


@pytest.fixture
async def miscounting(
    pg_session_factory: async_sessionmaker[AsyncSession], catalog: _Catalog
) -> AsyncIterator[AsyncClient]:
    catalog.available = frozenset({"STXUSDT"})
    async for api in _delete_client(pg_session_factory, catalog, miscounting=True):
        yield api


async def _seed_signal(
    pg_session_factory: async_sessionmaker[AsyncSession],
    strategy_id: UUID,
    reservation: bool = False,
) -> None:
    """One signal as the alert spells it (``STXUSDT.P``), and optionally a
    reservation on it, by plain SQL."""
    signal_id = uuid4()
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO signals (id, strategy_id, idempotency_key, raw_payload, "
                "action, contracts, position_size, price, symbol, signal_type) "
                "VALUES (:id, :strategy_id, :key, '{}'::jsonb, 'buy', 1, 1, 1, 'STXUSDT.P', "
                ":signal_type)"
            ),
            {
                "id": signal_id,
                "strategy_id": strategy_id,
                "key": f"k-{signal_id}",
                "signal_type": str(strategy_id),
            },
        )
        if reservation:
            await session.execute(
                text(
                    "INSERT INTO reservations (id, strategy_id, signal_id, exchange, venue, "
                    "settlement_currency, amount, status, expires_at) "
                    "VALUES (:id, :strategy_id, :signal_id, 'pionex', 'spot', 'USDT', 100, "
                    "'RELEASED', now() + interval '30 seconds')"
                ),
                {"id": uuid4(), "strategy_id": strategy_id, "signal_id": signal_id},
            )
        await session.commit()


async def test_delete_a_strategy_with_no_history_204_no_body_and_get_is_404_afterwards(
    deleting: AsyncClient,
) -> None:
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])

    response = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 204
    assert response.content == b""
    assert (await deleting.get(f"/strategies/{strategy_id}", headers=_auth())).status_code == 404


async def test_delete_unknown_id_404(deleting: AsyncClient) -> None:
    unknown = uuid4()

    response = await deleting.delete(f"/strategies/{unknown}", headers=_auth())

    assert response.status_code == 404
    assert response.json()["detail"] == f"no strategy registered under id {unknown}"


async def test_delete_repeated_404(deleting: AsyncClient) -> None:
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])

    first = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())
    second = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert (first.status_code, second.status_code) == (204, 404)


async def test_delete_enabled_409_still_enabled_and_the_strategy_remains_enabled(
    deleting: AsyncClient,
) -> None:
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])
    await deleting.patch(f"/strategies/{strategy_id}", json={"enabled": True}, headers=_auth())

    response = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "STILL_ENABLED"
    kept = await deleting.get(f"/strategies/{strategy_id}", headers=_auth())
    assert kept.status_code == 200
    assert kept.json()["enabled"] is True


async def test_delete_with_history_409_has_history_carries_all_six_integer_counts(
    deleting: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])
    await _seed_signal(pg_session_factory, strategy_id)

    response = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "HAS_HISTORY"
    assert isinstance(detail["message"], str)
    assert detail["history"] == _history_body(signals=1)
    assert all(type(count) is int for count in detail["history"].values())
    assert (await deleting.get(f"/strategies/{strategy_id}", headers=_auth())).status_code == 200


async def _toggle(api: AsyncClient, strategy_id: str) -> None:
    for enabled in (True, False):
        toggled = await api.patch(
            f"/strategies/{strategy_id}", json={"enabled": enabled}, headers=_auth()
        )
        assert toggled.status_code == 200


async def test_delete_a_toggled_strategy_204(deleting: AsyncClient) -> None:
    # Owner answer Q1 (decision 42), migration 0028: enablement events are not
    # history. This module's ORM schema has no foreign key on them, so what it
    # proves is the HTTP outcome; the cascade itself is proven on ``head`` in
    # ``test_delete_strategy_integration.py``.
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])
    await _toggle(deleting, strategy_id)

    response = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 204
    assert (await deleting.get(f"/strategies/{strategy_id}", headers=_auth())).status_code == 404


async def test_delete_a_toggled_strategy_with_a_signal_409_still_reports_its_events(
    deleting: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Events are reported, never the cause: the signal refuses, and the body keeps
    all six counts, the events' among them."""
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])
    await _toggle(deleting, strategy_id)
    await _seed_signal(pg_session_factory, strategy_id)

    response = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 409
    assert response.json()["detail"]["history"] == _history_body(signals=1, enablement_events=2)


async def test_delete_database_refusal_is_409_has_history_never_500(
    miscounting: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    strategy_id = await _register(miscounting, allowed_pairs=["STXUSDT"])
    await _seed_signal(pg_session_factory, strategy_id, reservation=True)

    with caplog.at_level(logging.WARNING):
        response = await miscounting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "HAS_HISTORY"
    assert detail["history"] == _history_body()
    assert "reservations_strategy_id_fkey" in detail["message"]
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert "reservations_strategy_id_fkey" in errors[0].getMessage()
    kept = await miscounting.get(f"/strategies/{strategy_id}", headers=_auth())
    assert kept.status_code == 200


async def test_after_a_delete_events_performance_and_archive_answer_404(
    deleting: AsyncClient,
) -> None:
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])
    deleted = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())
    assert deleted.status_code == 204

    answers = {
        "events": await deleting.get(f"/strategies/{strategy_id}/events", headers=_auth()),
        "performance": await deleting.get(
            f"/performance/strategies/{strategy_id}", headers=_auth()
        ),
        "trades": await deleting.get(
            f"/performance/strategies/{strategy_id}/trades", headers=_auth()
        ),
        "archive": await deleting.post(f"/strategies/{strategy_id}/archive", headers=_auth()),
    }

    assert {name: r.status_code for name, r in answers.items()} == dict.fromkeys(answers, 404)


async def test_a_deleted_id_registers_again_201_with_zero_uptime(deleting: AsyncClient) -> None:
    strategy_id = await _register(deleting, name="again", allowed_pairs=["STXUSDT"])
    deleted = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())
    assert deleted.status_code == 204

    response = await deleting.post(
        "/strategies",
        json=_post_body(id=str(strategy_id), name="again", allowed_pairs=["STXUSDT.P"]),
        headers=_auth(),
    )

    assert response.status_code == 201
    assert response.json()["uptime"] == {
        "seconds": 0.0,
        "first_enabled_at": None,
        "baseline": False,
    }
    events = await deleting.get(f"/strategies/{strategy_id}/events", headers=_auth())
    assert events.json() == []


async def test_a_refused_delete_leaves_the_session_usable_for_the_next_request(
    pg_session_factory: async_sessionmaker[AsyncSession], catalog: _Catalog
) -> None:
    """The database refusal aborts the transaction. Both requests share ONE
    session, so without the route's ``rollback()`` the next request fails on an
    aborted transaction instead of answering."""
    catalog.available = frozenset({"STXUSDT"})
    async with pg_session_factory() as shared:
        async for api in _delete_client(
            pg_session_factory, catalog, shared_session=shared, miscounting=True
        ):
            strategy_id = await _register(api, allowed_pairs=["STXUSDT"])
            await _seed_signal(pg_session_factory, strategy_id, reservation=True)

            refused = await api.delete(f"/strategies/{strategy_id}", headers=_auth())
            assert refused.status_code == 409
            after = await api.get(f"/strategies/{strategy_id}", headers=_auth())

            assert after.status_code == 200
            assert after.json()["id"] == str(strategy_id)


@pytest.mark.parametrize("refusal", ["still_enabled", "has_history"])
async def test_a_refused_delete_releases_the_row_lock_before_the_session_closes(
    refusal: str,
    pg_session_factory: async_sessionmaker[AsyncSession],
    catalog: _Catalog,
) -> None:
    """The use case takes the strategy row lock and raises without rolling back.
    The session is shared and still open, so only the route's ``rollback()``
    frees the row for another connection (``NOWAIT`` raises if it did not)."""
    catalog.available = frozenset({"STXUSDT"})
    async with pg_session_factory() as shared:
        async for api in _delete_client(pg_session_factory, catalog, shared_session=shared):
            strategy_id = await _register(api, allowed_pairs=["STXUSDT"])
            if refusal == "still_enabled":
                await api.patch(
                    f"/strategies/{strategy_id}", json={"enabled": True}, headers=_auth()
                )
            else:
                await _seed_signal(pg_session_factory, strategy_id)

            refused = await api.delete(f"/strategies/{strategy_id}", headers=_auth())
            assert refused.status_code == 409

            async with pg_session_factory() as other:
                row = await other.execute(
                    text("SELECT id FROM strategies WHERE id = :id FOR UPDATE NOWAIT"),
                    {"id": strategy_id},
                )
                assert row.scalar_one() == strategy_id


async def test_delete_archived_with_no_history_204(deleting: AsyncClient) -> None:
    # Q3 answered "yes" (decision 42): an archived strategy is still deletable.
    strategy_id = await _register(deleting, allowed_pairs=["STXUSDT"])
    archived = await deleting.post(f"/strategies/{strategy_id}/archive", headers=_auth())
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    response = await deleting.delete(f"/strategies/{strategy_id}", headers=_auth())

    assert response.status_code == 204
    assert (await deleting.get(f"/strategies/{strategy_id}", headers=_auth())).status_code == 404


# --------------------------------------------------------------------------
# 12f.9.7 -- the share in plain notation, and the PATCH's contract (design.md,
# unit 12f addendum, section C; spec: admin-api "The Strategy Update Takes The
# Share As A Plain Decimal And The Strategy View Serves It In Plain Notation").
#
# ``StrategyView.allocation_percent`` is written with the wire's plain
# notation, so a very small share is never an exponent (``1E-7``). The request
# bodies and the validation (0 < share <= 100) are unchanged.
# --------------------------------------------------------------------------


async def _set_stored_share(
    pg_session_factory: async_sessionmaker[AsyncSession], strategy_id: UUID, value: str
) -> None:
    """Writes the share straight to the column, which is an unscaled ``Numeric``."""
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET allocation_percent = CAST(:v AS numeric) WHERE id = :id"),
            {"v": value, "id": strategy_id},
        )
        await session.commit()


async def _share_of(client: AsyncClient, strategy_id: UUID) -> Any:
    response = await client.get(f"/strategies/{strategy_id}", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()["allocation_percent"]


async def _patch_share(client: AsyncClient, strategy_id: UUID, value: Any) -> Any:
    return await client.patch(
        f"/strategies/{strategy_id}", json={"allocation_percent": value}, headers=_auth()
    )


async def test_a_very_small_share_is_never_served_with_an_exponent(
    client: AsyncClient, pg_session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Stored ``0.0000001``: pydantic writes ``Decimal("0.0000001")`` as ``1E-7``
    unless the wire's plain notation is used. Read by GET, and answered by a
    PATCH of the same value."""
    strategy_id = await _register(client)
    await _set_stored_share(pg_session_factory, strategy_id, "0.0000001")

    got = await _share_of(client, strategy_id)
    patched = await _patch_share(client, strategy_id, "0.0000001")

    assert got == "0.0000001"
    assert patched.status_code == 200
    assert patched.json()["allocation_percent"] == "0.0000001"


async def test_a_decimal_share_is_saved_and_served_as_it_is(client: AsyncClient) -> None:
    strategy_id = await _register(client)

    patched = await _patch_share(client, strategy_id, "33.5")

    assert patched.status_code == 200
    assert patched.json()["allocation_percent"] == "33.5"
    assert await _share_of(client, strategy_id) == "33.5"


async def test_the_patch_answer_and_a_later_get_show_the_same_text(
    client: AsyncClient,
) -> None:
    strategy_id = await _register(client)

    patched = await _patch_share(client, strategy_id, "33.50")

    assert patched.status_code == 200
    assert patched.json()["allocation_percent"] == await _share_of(client, strategy_id)


async def test_a_share_below_one_is_accepted(client: AsyncClient) -> None:
    strategy_id = await _register(client)

    patched = await _patch_share(client, strategy_id, "0.5")

    assert patched.status_code == 200
    assert patched.json()["allocation_percent"] == "0.5"
    assert await _share_of(client, strategy_id) == "0.5"


async def test_a_share_of_exactly_100_is_accepted(client: AsyncClient) -> None:
    strategy_id = await _register(client, allocation_percent="40")

    patched = await _patch_share(client, strategy_id, "100")

    assert patched.status_code == 200
    assert patched.json()["allocation_percent"] == "100"
    assert await _share_of(client, strategy_id) == "100"


@pytest.mark.parametrize("value", ["0", "100.5", "abc"])
async def test_zero_above_100_and_a_text_that_is_not_a_decimal_are_422_and_the_stored_share_is_unchanged(  # noqa: E501
    client: AsyncClient, value: str
) -> None:
    strategy_id = await _register(client, allocation_percent="40")

    patched = await _patch_share(client, strategy_id, value)

    assert patched.status_code == 422
    assert await _share_of(client, strategy_id) == "40"


async def test_only_the_share_changes(client: AsyncClient) -> None:
    strategy_id = await _register(client, allowed_pairs=["ETHUSDT", "SOLUSDT"])
    enabled = await client.patch(
        f"/strategies/{strategy_id}", json={"enabled": True}, headers=_auth()
    )
    assert enabled.status_code == 200
    before = (await client.get(f"/strategies/{strategy_id}", headers=_auth())).json()

    patched = await _patch_share(client, strategy_id, "25")

    assert patched.status_code == 200
    after = patched.json()
    assert after["allocation_percent"] == "25"
    assert after["enabled"] is True
    assert after["allowed_pairs"] == ["ETHUSDT", "SOLUSDT"]
    unchanged = ("id", "name", "exchange", "venue", "settlement_currency", "fill_mode")
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}
    assert after["archived_at"] is None


async def test_a_disabled_strategys_share_is_accepted_and_it_stays_disabled(
    client: AsyncClient,
) -> None:
    strategy_id = await _register(client)
    assert (await client.get(f"/strategies/{strategy_id}", headers=_auth())).json()[
        "enabled"
    ] is False

    patched = await _patch_share(client, strategy_id, "12.5")

    assert patched.status_code == 200
    assert patched.json()["allocation_percent"] == "12.5"
    assert patched.json()["enabled"] is False


async def test_patching_an_unknown_strategy_is_404_with_its_existing_body(
    client: AsyncClient,
) -> None:
    unknown = uuid4()

    response = await _patch_share(client, unknown, "25")

    assert response.status_code == 404
    assert response.json() == {"detail": f"no strategy registered under id {unknown}"}

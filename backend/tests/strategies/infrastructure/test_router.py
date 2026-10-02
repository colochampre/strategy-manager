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

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared.config import get_settings
from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
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

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.asked.append(pool)
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

    app = _app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app)
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

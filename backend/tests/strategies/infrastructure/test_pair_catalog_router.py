"""``GET /pools/{exchange}/{venue}/{ccy}/available-pairs`` (design addendum § F).

Mirrors ``test_router.py``: a bare ``FastAPI()`` with only this router mounted,
the admin token set explicitly, ``get_session`` over real PostgreSQL (pool
existence is a real ``capital_pools`` read) and ``get_pair_catalog`` overridden
with a fake, so no test touches a network or needs a credential. The two tests
that exercise the REAL ``VenuePairCatalog`` drive it over ``httpx.MockTransport``.

Symbol spelling across the boundary: the fake venue lists ``STXUSDT_PERP`` or
``STXUSDT.P`` where the answer is the ``market_key`` form ``STXUSDT``.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.strategies.application.ports import PoolKey
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
)
from strategy_manager.strategies.infrastructure.pair_catalog import VenuePairCatalog
from strategy_manager.strategies.infrastructure.pair_catalog_router import (
    get_pair_catalog,
)
from strategy_manager.strategies.infrastructure.pair_catalog_router import (
    router as pair_catalog_router,
)
from tests.shared.infrastructure.binance.test_futures_rules import AAVE
from tests.shared.infrastructure.bybit.test_read_client import BTC_PERP

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"
BYBIT = "/pools/bybit/usdt-m/USDT/available-pairs"
PIONEX_SPOT = "/pools/pionex/spot/USDT/available-pairs"


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _Catalog:
    """A fake ``PairCatalogPort`` that records every pool it is asked for."""

    def __init__(
        self,
        answers: dict[PoolKey, frozenset[str]] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.answers = answers or {}
        self.failure = failure
        self.asked: list[PoolKey] = []

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.asked.append(pool)
        if self.failure is not None:
            raise self.failure
        return self.answers.get(pool, frozenset())


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


def _app(
    pg_session_factory: async_sessionmaker[AsyncSession], catalog: Any
) -> FastAPI:
    app = FastAPI()
    app.include_router(pair_catalog_router)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    app.dependency_overrides[get_pair_catalog] = lambda: catalog
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_available_pairs_200_sorted_with_pool_and_count(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    catalog = _Catalog({("bybit", "usdt-m", "USDT"): frozenset({"STXUSDT", "AAVEUSDT", "BTCUSDT"})})

    async with _client(_app(pg_session_factory, catalog)) as api:
        response = await api.get(BYBIT, headers=_auth())

    assert response.status_code == 200
    assert response.json() == {
        "pool": {"exchange": "bybit", "venue": "usdt-m", "settlement_currency": "USDT"},
        "pairs": ["AAVEUSDT", "BTCUSDT", "STXUSDT"],
        "count": 3,
    }
    assert catalog.asked == [("bybit", "usdt-m", "USDT")]


async def test_unknown_pool_404_and_the_catalogue_is_never_asked(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = _Catalog({("bybit", "usdt-m", "BTC"): frozenset({"BTCUSDT"})})

    async with _client(_app(pg_session_factory, catalog)) as api:
        for path in (
            "/pools/bybit/usdt-m/BTC/available-pairs",  # a currency the pool has no row for
            "/pools/bybit/usdt-m/usdt/available-pairs",  # wrong case
            "/pools/kraken/spot/USDT/available-pairs",  # an exchange nobody configured
        ):
            response = await api.get(path, headers=_auth())

            assert response.status_code == 404, path
            assert response.json() == {"detail": "no such pool"}

    assert catalog.asked == []
    refusals = [
        r for r in caplog.records if r.levelname == "WARNING" and "no such pool" in r.message
    ]
    assert len(refusals) == 3


async def test_disabled_pool_200(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false "
                "WHERE exchange = 'bybit' AND venue = 'usdt-m'"
            )
        )
        await session.commit()
    catalog = _Catalog({("bybit", "usdt-m", "USDT"): frozenset({"STXUSDT"})})

    async with _client(_app(pg_session_factory, catalog)) as api:
        response = await api.get(BYBIT, headers=_auth())

    assert response.status_code == 200
    assert response.json()["pairs"] == ["STXUSDT"]


async def test_unserved_pool_404_pair_catalogue_not_served_not_an_empty_list(
    pg_session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = _Catalog(failure=PairCatalogNotServed("no catalogue for pionex/spot"))

    async with _client(_app(pg_session_factory, catalog)) as api:
        response = await api.get(PIONEX_SPOT, headers=_auth())

    assert response.status_code == 404
    body = response.json()
    assert body["detail"]["error"] == "PAIR_CATALOGUE_NOT_SERVED"
    assert body["detail"]["message"]
    assert "pairs" not in body
    assert body != {"detail": "no such pool"}  # distinguishable from an unknown pool
    assert any(
        r.levelname == "WARNING" and "not served" in r.message for r in caplog.records
    )


async def test_the_real_catalogue_refuses_a_pool_with_no_source_without_any_venue_call(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    real = VenuePairCatalog.for_settings(_settings(), transport=httpx.MockTransport(handler))

    async with _client(_app(pg_session_factory, real)) as api:
        response = await api.get(PIONEX_SPOT, headers=_auth())

    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "PAIR_CATALOGUE_NOT_SERVED"
    assert calls == []


async def test_venue_unreachable_502_pair_catalogue_unavailable(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    catalog = _Catalog(failure=PairCatalogUnavailable("the pair list could not be read"))

    async with _client(_app(pg_session_factory, catalog)) as api:
        response = await api.get(BYBIT, headers=_auth())

    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["error"] == "PAIR_CATALOGUE_UNAVAILABLE"
    assert body["detail"]["message"]
    assert "pairs" not in body


async def test_no_token_is_401_before_the_catalogue_is_asked(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    catalog = _Catalog({("bybit", "usdt-m", "USDT"): frozenset({"STXUSDT"})})

    async with _client(_app(pg_session_factory, catalog)) as api:
        missing = await api.get(BYBIT)
        wrong = await api.get(BYBIT, headers=_auth("not-the-token"))

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert catalog.asked == []


async def test_one_pools_request_never_returns_another_pools_pairs(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    catalog = _Catalog(
        {
            ("bybit", "usdt-m", "USDT"): frozenset({"STXUSDT"}),
            ("pionex", "coin-m", "BTC"): frozenset({"BTCUSD"}),
            ("pionex", "coin-m", "ETH"): frozenset({"ETHUSD"}),
        }
    )

    async with _client(_app(pg_session_factory, catalog)) as api:
        usdt = await api.get(BYBIT, headers=_auth())
        btc = await api.get("/pools/pionex/coin-m/BTC/available-pairs", headers=_auth())
        eth = await api.get("/pools/pionex/coin-m/ETH/available-pairs", headers=_auth())

    assert [r.json()["pairs"] for r in (usdt, btc, eth)] == [["STXUSDT"], ["BTCUSD"], ["ETHUSD"]]
    assert catalog.asked == [
        ("bybit", "usdt-m", "USDT"),
        ("pionex", "coin-m", "BTC"),
        ("pionex", "coin-m", "ETH"),
    ]


def _settings(**overrides: Any) -> Settings:
    base: Settings = get_settings()
    return base.model_copy(
        update={
            "bybit_base_url": "https://bybit.example.test",
            "binance_futures_base_url": "https://binance.example.test",
            **overrides,
        }
    )


def _venues(
    recorded: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if request.url.host == "bybit.example.test":
            listing = [{**BTC_PERP, "symbol": "STXUSDT"}]
            return httpx.Response(
                200, json={"retCode": 0, "result": {"list": listing, "nextPageCursor": ""}}
            )
        return httpx.Response(200, json={"symbols": [AAVE]})

    return handler


async def test_the_real_catalogue_requests_only_the_configured_host_and_the_fixed_path(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorded: list[httpx.Request] = []
    real = VenuePairCatalog.for_settings(
        _settings(), transport=httpx.MockTransport(_venues(recorded))
    )

    async with _client(_app(pg_session_factory, real)) as api:
        response = await api.get(BYBIT, headers=_auth())

    assert response.status_code == 200
    assert response.json()["pairs"] == ["STXUSDT"]
    [request] = recorded
    assert request.url.host == "bybit.example.test"
    assert request.url.path == "/v5/market/instruments-info"
    assert dict(request.url.params) == {"category": "linear", "limit": "1000"}
    # The three path values only chose a registry entry and a filter value; none
    # of them is part of what was sent, and nothing authenticates the request.
    sent = str(request.url).lower()
    assert "usdt-m" not in sent
    assert "usdt" not in sent
    auth_markers = ("x-bapi", "x-mbx", "authorization")
    assert not any(h.lower().startswith(auth_markers) for h in request.headers)


async def test_binance_pool_reads_the_configured_futures_host_and_the_fixed_path(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO capital_pools (exchange, venue, settlement_currency, min_order_size) "
                "VALUES ('binance', 'usdt-m', 'USDT', 5)"
            )
        )
        await session.commit()
    recorded: list[httpx.Request] = []
    real = VenuePairCatalog.for_settings(
        _settings(), transport=httpx.MockTransport(_venues(recorded))
    )

    async with _client(_app(pg_session_factory, real)) as api:
        response = await api.get("/pools/binance/usdt-m/USDT/available-pairs", headers=_auth())

    assert response.status_code == 200
    assert response.json()["pairs"] == ["AAVEUSDT"]
    [request] = recorded
    assert request.url.host == "binance.example.test"
    assert request.url.path == "/fapi/v1/exchangeInfo"
    assert not any(h.lower().startswith(("x-mbx", "authorization")) for h in request.headers)
    assert "signature" not in request.url.params


async def test_the_composition_root_mounts_the_route_under_api_behind_the_token() -> None:
    """``main.py`` binds it: one ``VenuePairCatalog`` on ``app.state`` and the
    router inside ``api_router``. A live request, because this FastAPI resolves
    included routers lazily."""
    from strategy_manager.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        under_api = await api.get("/api/pools/bybit/usdt-m/USDT/available-pairs")
        pre_move = await api.get("/pools/bybit/usdt-m/USDT/available-pairs")

    assert under_api.status_code == 401  # reached the route, refused by its router's guard
    assert pre_move.status_code == 404  # never registered outside /api
    assert isinstance(app.state.pair_catalog, VenuePairCatalog)


class _Arrivals:
    """Counts the requests that reached the catalogue, then delegates."""

    def __init__(self, real: VenuePairCatalog) -> None:
        self._real = real
        self.arrived = 0

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]:
        self.arrived += 1
        return await self._real.available_pairs(pool)


async def test_n_concurrent_requests_make_one_venue_read(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    requests_to_venue = 0
    gate = asyncio.Event()

    async def parked_venue(request: httpx.Request) -> httpx.Response:
        nonlocal requests_to_venue
        requests_to_venue += 1
        await gate.wait()
        return _venues([])(request)

    arrivals = _Arrivals(
        VenuePairCatalog.for_settings(_settings(), transport=httpx.MockTransport(parked_venue))
    )
    n = 5

    async with _client(_app(pg_session_factory, arrivals)) as api:
        tasks = [asyncio.create_task(api.get(BYBIT, headers=_auth())) for _ in range(n)]
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(10):  # a hang guard, not a timing assertion
                while arrivals.arrived < n:
                    await asyncio.sleep(0)
        assert arrivals.arrived == n, "every request must reach the catalogue"
        for _ in range(50):  # every arrival is now past the cache check, at the lock
            await asyncio.sleep(0)

        assert requests_to_venue == 1
        assert not any(task.done() for task in tasks)

        gate.set()
        responses = await asyncio.gather(*tasks)

    assert [r.status_code for r in responses] == [200] * n
    assert {tuple(r.json()["pairs"]) for r in responses} == {("STXUSDT",)}
    assert requests_to_venue == 1

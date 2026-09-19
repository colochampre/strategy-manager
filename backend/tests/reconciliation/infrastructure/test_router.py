"""API tests for ``GET /reconciliation/discrepancies``.

Two things travel together here, exactly like
``tests/strategies/infrastructure/test_router_auth.py``: the bearer-token
guard (now shared, see ``shared/infrastructure/admin_auth.py``) refuses every
request without a valid token, discovered from the router itself rather than
a hand-written list; and, once authenticated, the endpoint reads real rows
back through ``SqlAlchemyDiscrepancyRepository`` rather than a fake -- the
whole point of decision 10 is that the router is a thin read over the port
Unit 1 already built and proved.

The trap this file is written to avoid: a row is confirmed NOW when
``status == 'CONFIRMED'``, never when ``confirmed_at IS NOT NULL`` (migration
``0020``); and "open" means ``resolved_at IS NULL``, a completely different
column from ``status``. The ``status`` QUERY parameter this endpoint accepts
(``open``/``resolved``/``all``) filters on ``resolved_at``; it has nothing to
do with the ``DiscrepancyStatus`` the response body's own ``status`` field
carries.
"""

import re
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.router import (
    router as reconciliation_router,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"
NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)

#: Path parameters are filled with a well-formed value so that a refusal is
#: never the path converter's doing.
_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _routes() -> list[tuple[str, str]]:
    """Every (method, path) this router serves, read from the router itself
    -- exactly the pattern ``test_router_auth.py`` uses for ``/strategies``."""
    pairs: list[tuple[str, str]] = []
    for route in reconciliation_router.routes:
        path = _PATH_PARAM.sub(str(uuid4()), getattr(route, "path", ""))
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            pairs.append((method, path))
    return pairs


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(reconciliation_router)
    return app


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


async def _authenticated_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    from strategy_manager.shared import db as shared_db

    app = _app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


@pytest.fixture
async def authenticated_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    async for api in _authenticated_client(pg_session_factory):
        yield api


def _observation(
    kind: DiscrepancyKind = DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
    venue_net_base: Decimal = Decimal("2.0"),
    ledger_net_base: Decimal = Decimal("1.5"),
) -> Observation:
    return Observation(kind=kind, venue_net_base=venue_net_base, ledger_net_base=ledger_net_base)


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pool: tuple[str, str, str],
    symbol: str,
    status: DiscrepancyStatus = DiscrepancyStatus.OBSERVED,
    resolve: bool = False,
) -> None:
    scan_id = uuid4()
    async with session_factory() as session:
        repo = SqlAlchemyDiscrepancyRepository(session)
        await repo.upsert_open(
            pool,
            symbol,
            _observation(),
            [uuid4()],
            consecutive_scans=1,
            status=status,
            scan_id=scan_id,
            at=NOW,
        )
        if resolve:
            await repo.resolve_absent(pool, [symbol], scan_id, NOW)
        await session.commit()


async def test_there_is_at_least_one_route_to_protect() -> None:
    """Guards the enumeration itself: a test that iterates an empty list
    passes while proving nothing."""
    assert len(_routes()) >= 1


async def test_every_registered_route_refuses_a_request_without_a_token(
    client: AsyncClient,
) -> None:
    for method, path in _routes():
        response = await client.request(method, path)

        assert response.status_code == 401, f"{method} {path} was not refused"


async def test_no_route_leaks_which_part_of_the_credential_was_wrong(
    client: AsyncClient,
) -> None:
    details = set()
    for method, path in _routes():
        for headers in (
            {},
            {"Authorization": f"Bearer {TOKEN}-wrong"},
            {"Authorization": TOKEN},
        ):
            response = await client.request(method, path, headers=headers)

            assert response.status_code == 401
            details.add(response.json()["detail"])

    assert details == {UNAUTHORIZED_DETAIL}


async def test_authenticated_admin_lists_open_discrepancies_across_pools(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    """The spec scenario: two open discrepancies across different pools,
    both listed, each naming its pool and symbol."""
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="BTCUSDT",
    )
    await _seed(
        pg_session_factory,
        pool=("binance", "usdt-m", "USDT"),
        symbol="ETHUSDT",
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    pools_and_symbols = {
        (row["exchange"], row["venue"], row["settlement_currency"], row["symbol"])
        for row in body
    }
    assert pools_and_symbols == {
        ("bybit", "usdt-m", "USDT", "BTCUSDT"),
        ("binance", "usdt-m", "USDT", "ETHUSDT"),
    }


async def test_default_status_filter_excludes_resolved_discrepancies(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="OPENCOIN")
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="RESOLVEDCOIN",
        resolve=True,
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies", headers={"Authorization": f"Bearer {TOKEN}"}
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["OPENCOIN"]


async def test_status_resolved_returns_only_resolved_discrepancies(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    """The trap this test exists to catch: filtering must key on
    ``resolved_at``, never on the CONFIRMED/OBSERVED ``status`` column."""
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="OPENCOIN")
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="RESOLVEDCOIN",
        resolve=True,
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"status": "resolved"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["RESOLVEDCOIN"]


async def test_status_all_returns_both_open_and_resolved(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="OPENCOIN")
    await _seed(
        pg_session_factory,
        pool=("bybit", "usdt-m", "USDT"),
        symbol="RESOLVEDCOIN",
        resolve=True,
    )

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"status": "all"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert {row["symbol"] for row in response.json()} == {"OPENCOIN", "RESOLVEDCOIN"}


async def test_limit_bounds_the_number_of_rows_returned(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    for i in range(3):
        await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol=f"COIN{i}")

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"limit": 2},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_limit_above_the_max_is_rejected(
    authenticated_client: AsyncClient,
) -> None:
    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"limit": 501},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 422


async def test_exchange_venue_settlement_currency_and_symbol_filter_independently(
    pg_session_factory: async_sessionmaker[AsyncSession],
    authenticated_client: AsyncClient,
) -> None:
    await _seed(pg_session_factory, pool=("bybit", "usdt-m", "USDT"), symbol="BTCUSDT")
    await _seed(pg_session_factory, pool=("binance", "usdt-m", "USDT"), symbol="ETHUSDT")

    response = await authenticated_client.get(
        "/reconciliation/discrepancies",
        params={"exchange": "bybit"},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["BTCUSDT"]

"""A share of the pool has at most 18 decimal places, wherever the API takes one
(owner decision 50; spec: admin-api; tasks.md 12f.9.17).

Three inputs take a share: the ``share`` query of ``GET /api/strategies/{id}/share-preview``,
``allocation_percent`` of the update (``PATCH``) and ``allocation_percent`` of the
registration (``POST``). A value whose WRITTEN form has more than 18 decimal places is
refused with the application's 422 that echoes no input, and nothing is stored. The count
is of the value as written: trailing zeros count (``1.5000000000000000000`` has 19) and
``1E+1`` has none.

Mounted through ``create_app()`` so the application's redacted 422 handler is part of what
is proven, over real PostgreSQL (the ORM schema of ``tests/ledger/infrastructure/conftest.py``).
``raise_app_exceptions=False`` makes a route that fails answer its 500 instead of raising
into the test, so what the route answered is what the assertion reads.
"""

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.strategies.infrastructure.test_share_preview_router import _strategy, _synced

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"
Factory = async_sessionmaker[AsyncSession]

#: More than 18 decimal places AS WRITTEN. The last two are the spellings a
#: ``normalize()`` would hide: a trailing zero past the eighteenth place, and an exponent.
#: ``1e-20000`` is past what PostgreSQL's NUMERIC can hold (a scale of 16383).
REFUSED = ["1e-19", "0.0000000000000000001", "1.5000000000000000000", "1e-20000"]

#: (as written, what it is worth). Exactly 18 decimals, an exponent that is not a
#: decimal place at all, and ordinary shares.
ACCEPTED = [
    ("1e-18", Decimal("0.000000000000000001")),
    ("0.123456789012345678", Decimal("0.123456789012345678")),
    ("1.500000000000000000", Decimal("1.5")),
    ("1E+1", Decimal(10)),
    ("0.5", Decimal("0.5")),
]


class _Catalog:
    async def available_pairs(self, pool: tuple[str, str, str]) -> frozenset[str]:
        return frozenset({"ETHUSDT"})


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


@pytest.fixture
async def client(pg_session_factory: Factory) -> AsyncIterator[AsyncClient]:  # noqa: F811
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    app.dependency_overrides[get_pair_catalog] = _Catalog
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as api:
        yield api


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


async def _preview(client: AsyncClient, strategy_id: UUID, value: str) -> Any:
    return await client.get(
        f"/api/strategies/{strategy_id}/share-preview", params={"share": value}, headers=_auth()
    )


async def _patch(client: AsyncClient, strategy_id: UUID, value: str) -> Any:
    return await client.patch(
        f"/api/strategies/{strategy_id}", json={"allocation_percent": value}, headers=_auth()
    )


async def _register(client: AsyncClient, strategy_id: UUID, value: str) -> Any:
    return await client.post(
        "/api/strategies",
        json={
            "id": str(strategy_id),
            "name": f"strategy-{strategy_id}",
            "exchange": "bybit",
            "venue": "usdt-m",
            "settlement_currency": "USDT",
            "fill_mode": "PARTIAL",
            "allocation_percent": value,
            "allowed_pairs": ["ETHUSDT"],
        },
        headers=_auth(),
    )


async def _stored_share(factory: Factory, strategy_id: UUID) -> Decimal | None:
    async with factory() as session:
        value = await session.scalar(
            text("SELECT allocation_percent FROM strategies WHERE id = :id"), {"id": strategy_id}
        )
    assert value is None or isinstance(value, Decimal)
    return value


def _assert_refused_without_echo(response: Any, value: str) -> None:
    assert response.status_code == 422
    assert "input" not in response.text
    assert value not in response.text, "the rejected value was echoed"
    assert len(response.text) < 2000


# --- the preview's ``share`` -----------------------------------------------------------------


@pytest.mark.parametrize("value", REFUSED)
async def test_the_preview_refuses_a_share_with_more_than_18_decimals(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    value: str,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id, value)

    _assert_refused_without_echo(response, value)


@pytest.mark.parametrize(("value", "worth"), ACCEPTED)
async def test_the_preview_accepts_a_share_with_at_most_18_decimals(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    value: str,
    worth: Decimal,
) -> None:
    strategy_id = await _strategy(pg_session_factory)
    await _synced(pg_session_factory)

    response = await _preview(client, strategy_id, value)

    assert response.status_code == 200, response.text
    assert Decimal(response.json()["exact"]["share"]) == worth


# --- the update's ``allocation_percent`` -------------------------------------------------------


@pytest.mark.parametrize("value", REFUSED)
async def test_the_update_refuses_a_share_with_more_than_18_decimals_and_stores_nothing(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    value: str,
) -> None:
    strategy_id = await _strategy(pg_session_factory, share="30")

    response = await _patch(client, strategy_id, value)

    _assert_refused_without_echo(response, value)
    assert await _stored_share(pg_session_factory, strategy_id) == Decimal(30)


@pytest.mark.parametrize(("value", "worth"), ACCEPTED)
async def test_the_update_accepts_a_share_with_at_most_18_decimals(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    value: str,
    worth: Decimal,
) -> None:
    strategy_id = await _strategy(pg_session_factory, share="30")

    response = await _patch(client, strategy_id, value)

    assert response.status_code == 200, response.text
    assert Decimal(response.json()["allocation_percent"]) == worth
    assert "e" not in response.json()["allocation_percent"].lower()
    assert await _stored_share(pg_session_factory, strategy_id) == worth


# --- the registration's ``allocation_percent`` ----------------------------------------------------


@pytest.mark.parametrize("value", REFUSED)
async def test_the_registration_refuses_a_share_with_more_than_18_decimals_and_creates_nothing(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    value: str,
) -> None:
    strategy_id = uuid4()

    response = await _register(client, strategy_id, value)

    _assert_refused_without_echo(response, value)
    assert await _stored_share(pg_session_factory, strategy_id) is None


@pytest.mark.parametrize(("value", "worth"), ACCEPTED)
async def test_the_registration_accepts_a_share_with_at_most_18_decimals(
    client: AsyncClient,
    pg_session_factory: Factory,  # noqa: F811
    value: str,
    worth: Decimal,
) -> None:
    strategy_id = uuid4()

    response = await _register(client, strategy_id, value)

    assert response.status_code == 201, response.text
    assert Decimal(response.json()["allocation_percent"]) == worth
    assert await _stored_share(pg_session_factory, strategy_id) == worth

"""API tests for ``GET /api/pools`` [DB] (design.md section 14; tasks.md 7.1).

Mounted through ``create_app()`` so the ``/api`` prefix is part of what is
proven, with ``get_session`` overridden to a real PostgreSQL session: the
router reads real rows back through the real adapter, never a fake.

**What "reserved" means here.** It is the allocator's own figure: the sum of
``reservations.amount`` for the pool where the status is PENDING or SUBMITTED
and ``expires_at`` is still in the future. A reservation that has FILLED,
been RELEASED or EXPIRED no longer holds capital, and neither does a PENDING one
past its expiry that the sweeper has not yet marked.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from strategy_manager.shared.infrastructure.admin_auth import UNAUTHORIZED_DETAIL
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_reservation,
    seed_signal,
    seed_strategy,
)

pytestmark = pytest.mark.integration

TOKEN = "adm1n-t0ken"


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "admin_api_token", TOKEN)


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


async def _snapshot(
    factory: async_sessionmaker[AsyncSession],
    exchange: str,
    venue: str,
    currency: str,
    *,
    total: str,
    available: str,
    observed_at: datetime | None = None,
) -> None:
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO pool_balance_snapshots "
                "(exchange, venue, settlement_currency, total, available, observed_at) "
                "VALUES (:e, :v, :c, :total, :available, :observed_at)"
            ),
            {
                "e": exchange,
                "v": venue,
                "c": currency,
                "total": Decimal(total),
                "available": Decimal(available),
                "observed_at": observed_at or datetime.now(UTC),
            },
        )
        await session.commit()


async def _reserve(
    factory: async_sessionmaker[AsyncSession],
    exchange: str,
    venue: str,
    currency: str,
    amount: str,
    *,
    status: str = "PENDING",
    expires_in: timedelta = timedelta(hours=1),
    strategy_id: UUID | None = None,
) -> None:
    if strategy_id is None:
        strategy_id = uuid4()
        await seed_strategy(
            factory,
            strategy_id=strategy_id,
            exchange=exchange,
            venue=venue,
            settlement_currency=currency,
        )
    signal_id = uuid4()
    await seed_signal(
        factory, signal_id=signal_id, strategy_id=strategy_id, idempotency_key=f"k-{signal_id}"
    )
    await seed_reservation(
        factory,
        reservation_id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        amount=Decimal(amount),
        status=status,
        expires_at=datetime.now(UTC) + expires_in,
    )


class _Pools(dict[tuple[str, str, str], dict[str, Any]]):
    """A missing pool is a failed ASSERTION (the body is wrong), not a KeyError."""

    def __missing__(self, key: tuple[str, str, str]) -> dict[str, Any]:
        raise AssertionError(f"pool {key} is not in the response; it holds {sorted(self)}")


def _by_pool(body: list[dict[str, Any]]) -> _Pools:
    return _Pools({(p["exchange"], p["venue"], p["settlement_currency"]): p for p in body})


async def test_get_pools_requires_bearer_token(client: AsyncClient) -> None:
    """Every refusal is the same 401, and the route lives under ``/api`` only."""
    missing = await client.get("/api/pools")
    wrong = await client.get("/api/pools", headers={"Authorization": f"Bearer {TOKEN}-wrong"})
    pre_move = await client.get("/pools", headers=_auth())
    admitted = await client.get("/api/pools", headers=_auth())

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["detail"] == UNAUTHORIZED_DETAIL
    assert pre_move.status_code == 404
    assert admitted.status_code == 200


async def test_get_pools_computes_allocatable_as_max_zero_available_minus_reserved_server_side(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Two pools, one with headroom and one over-reserved: the second is
    clamped to zero, never negative. The client is handed the answer."""
    await _snapshot(pg_session_factory, "bybit", "usdt-m", "USDT", total="500", available="100")
    await _reserve(pg_session_factory, "bybit", "usdt-m", "USDT", "10", status="PENDING")
    await _reserve(pg_session_factory, "bybit", "usdt-m", "USDT", "20", status="SUBMITTED")

    await _snapshot(pg_session_factory, "pionex", "spot", "USDT", total="50", available="10")
    await _reserve(pg_session_factory, "pionex", "spot", "USDT", "25", status="SUBMITTED")

    response = await client.get("/api/pools", headers=_auth())

    pools = _by_pool(response.json())
    bybit = pools[("bybit", "usdt-m", "USDT")]
    pionex = pools[("pionex", "spot", "USDT")]
    assert Decimal(bybit["reserved"]) == Decimal("30")
    assert Decimal(bybit["allocatable"]) == Decimal("70")
    assert Decimal(pionex["reserved"]) == Decimal("25")
    assert Decimal(pionex["allocatable"]) == Decimal("0")


async def test_get_pools_reserved_counts_only_live_reservations(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Reserved is the allocator's ``sum_active``: PENDING/SUBMITTED and not
    yet expired. A FILLED, RELEASED or EXPIRED row, and a PENDING row past its
    expiry, hold nothing."""
    await _snapshot(pg_session_factory, "bybit", "usdt-m", "USDT", total="500", available="400")
    await _reserve(pg_session_factory, "bybit", "usdt-m", "USDT", "7", status="PENDING")
    await _reserve(pg_session_factory, "bybit", "usdt-m", "USDT", "1000", status="FILLED")
    await _reserve(pg_session_factory, "bybit", "usdt-m", "USDT", "2000", status="EXPIRED")
    await _reserve(
        pg_session_factory,
        "bybit",
        "usdt-m",
        "USDT",
        "3000",
        status="PENDING",
        expires_in=timedelta(seconds=-5),
    )

    response = await client.get("/api/pools", headers=_auth())

    bybit = _by_pool(response.json())[("bybit", "usdt-m", "USDT")]
    assert Decimal(bybit["reserved"]) == Decimal("7")
    assert Decimal(bybit["allocatable"]) == Decimal("393")


async def test_get_pools_never_sums_two_pools_on_same_exchange(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """Rule 7. Pionex has three pools here (spot/USDT, coin-m/BTC, coin-m/ETH).
    Each is its own object with its own figures, a reservation in one never
    reaches another, and nothing in the body is a total."""
    await _snapshot(pg_session_factory, "pionex", "spot", "USDT", total="1000", available="900")
    await _snapshot(pg_session_factory, "pionex", "coin-m", "BTC", total="2", available="1")
    await _snapshot(pg_session_factory, "pionex", "coin-m", "ETH", total="30", available="20")
    await _reserve(pg_session_factory, "pionex", "spot", "USDT", "100", status="SUBMITTED")
    await _reserve(pg_session_factory, "pionex", "coin-m", "BTC", "0.25", status="PENDING")

    response = await client.get("/api/pools", headers=_auth())

    body = response.json()
    assert isinstance(body, list)
    pionex = [p for p in body if p["exchange"] == "pionex"]
    assert len(pionex) == 3
    pools = _by_pool(body)
    assert Decimal(pools[("pionex", "spot", "USDT")]["allocatable"]) == Decimal("800")
    assert Decimal(pools[("pionex", "coin-m", "BTC")]["allocatable"]) == Decimal("0.75")
    assert Decimal(pools[("pionex", "coin-m", "ETH")]["allocatable"]) == Decimal("20")
    assert Decimal(pools[("pionex", "coin-m", "ETH")]["reserved"]) == Decimal("0")
    # No element is an aggregate: every one is a single pool and carries the
    # same keys, and no key names a total across pools.
    assert {frozenset(p) for p in body} == {
        frozenset(
            {
                "exchange",
                "venue",
                "settlement_currency",
                "enabled",
                "balance",
                "reserved",
                "allocatable",
            }
        )
    }


async def test_get_pools_pool_without_a_snapshot_has_null_balance_and_null_allocatable(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """A pool nothing has synced has no available balance to subtract from, so
    its allocatable is unknown (null), not a fabricated zero."""
    await _snapshot(pg_session_factory, "bybit", "usdt-m", "USDT", total="500", available="100")
    await _reserve(pg_session_factory, "pionex", "spot", "USDT", "40", status="PENDING")

    response = await client.get("/api/pools", headers=_auth())

    pools = _by_pool(response.json())
    unsynced = pools[("pionex", "spot", "USDT")]
    assert unsynced["balance"] is None
    assert unsynced["allocatable"] is None
    assert Decimal(unsynced["reserved"]) == Decimal("40")
    assert pools[("bybit", "usdt-m", "USDT")]["balance"] is not None


async def test_get_pools_balance_carries_observed_at_utc_and_stale_flag(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """``stale`` uses the allocator's own limit (``balance_snapshot_max_age_seconds``),
    so a snapshot the allocator would refuse is flagged as stale."""
    limit = get_settings().balance_snapshot_max_age_seconds
    now = datetime.now(UTC)
    await _snapshot(
        pg_session_factory, "bybit", "usdt-m", "USDT", total="5", available="5", observed_at=now
    )
    await _snapshot(
        pg_session_factory,
        "pionex",
        "spot",
        "USDT",
        total="5",
        available="5",
        observed_at=now - timedelta(seconds=limit + 60),
    )

    response = await client.get("/api/pools", headers=_auth())

    pools = _by_pool(response.json())
    fresh = pools[("bybit", "usdt-m", "USDT")]["balance"]
    stale = pools[("pionex", "spot", "USDT")]["balance"]
    assert fresh["stale"] is False
    assert stale["stale"] is True
    observed = datetime.fromisoformat(fresh["observed_at"])
    assert observed.utcoffset() == timedelta(0)


async def test_get_pools_money_is_json_strings_and_disabled_pools_are_listed(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with pg_session_factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = false "
                "WHERE exchange = 'pionex' AND venue = 'coin-m' AND settlement_currency = 'ETH'"
            )
        )
        await session.commit()
    await _snapshot(pg_session_factory, "bybit", "usdt-m", "USDT", total="500", available="100")

    response = await client.get("/api/pools", headers=_auth())

    pools = _by_pool(response.json())
    assert len(pools) == 4
    assert pools[("pionex", "coin-m", "ETH")]["enabled"] is False
    assert pools[("bybit", "usdt-m", "USDT")]["enabled"] is True
    synced = pools[("bybit", "usdt-m", "USDT")]
    for value in (
        synced["balance"]["total"],
        synced["balance"]["available"],
        synced["reserved"],
        synced["allocatable"],
    ):
        assert isinstance(value, str)

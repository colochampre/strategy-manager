"""API tests for POST /webhook/tradingview.

Covers spec: signal-ingress § Webhook Authentication, § Idempotent Signal
Persistence, § Fast Enqueue-Only Response.

The current alert contract has no room for a shared secret in the fixed
Pionex-format body, so the secret travels as a query parameter on the
configured webhook URL. Which address the allowlist judges depends on
deployment: the request's peer address when exposed directly, and
``CF-Connecting-IP`` behind a Cloudflare Tunnel.

``ExchangePort`` does not exist until slice 5, so "no exchange call"
is verified indirectly here: the enqueued job is left PENDING (unclaimed),
proving nothing beyond persist-and-enqueue happened inline.
"""

import time
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.models import JobRow

pytestmark = pytest.mark.integration

ALLOWED_IP = "52.89.214.238"
DISALLOWED_IP = "203.0.113.9"
SECRET = "test-webhook-secret"

VALID_PAYLOAD = {
    "data": {"action": "buy", "contracts": "10", "position_size": "10"},
    "price": "50000.5",
    "signal_param": "{}",
    "signal_type": "a6a28229-9286-463f-99e8-5f48eb597d19",
    "symbol": "BTCUSDT",
    "time": "2026-08-12T10:15:30Z",
}


@pytest.fixture(autouse=True)
def _configure_webhook_secret() -> AsyncIterator[None]:
    get_settings().webhook_secret = SECRET
    yield
    get_settings().webhook_secret = ""


@pytest.fixture
async def api_client(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    from strategy_manager.shared import db as shared_db

    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, client=(ALLOWED_IP, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_valid_signal_returns_200_fast_and_never_touches_an_exchange(
    api_client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    start = time.monotonic()
    response = await api_client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=VALID_PAYLOAD
    )
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert elapsed < 3.0
    body = response.json()
    assert body["accepted"] is True
    assert body["duplicate"] is False
    UUID(body["signal_id"])  # a real UUID was returned

    async with pg_session_factory() as session:
        jobs = (await session.execute(select(JobRow))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].status == "PENDING"  # nothing executed it inline


async def test_wrong_source_ip_is_rejected_with_401(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from strategy_manager.shared import db as shared_db

    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, client=(DISALLOWED_IP, 12345))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/tradingview", params={"secret": SECRET}, json=VALID_PAYLOAD
        )

    assert response.status_code == 401

    async with pg_session_factory() as session:
        jobs = (await session.execute(select(JobRow))).scalars().all()
    assert jobs == []


async def test_missing_idempotency_inputs_are_rejected_with_422(api_client: AsyncClient) -> None:
    malformed_payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "data"}

    response = await api_client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=malformed_payload
    )

    assert response.status_code == 422


async def test_duplicate_signal_returns_200_with_no_second_job(
    api_client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await api_client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=VALID_PAYLOAD
    )
    second = await api_client.post(
        "/webhook/tradingview", params={"secret": SECRET}, json=VALID_PAYLOAD
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["signal_id"] == first.json()["signal_id"]
    assert second.json()["duplicate"] is True

    async with pg_session_factory() as session:
        jobs = (await session.execute(select(JobRow))).scalars().all()
    assert len(jobs) == 1


# --- behind a Cloudflare Tunnel --------------------------------------------
#
# The peer is cloudflared over the loopback, so reading the peer address would
# 401 every genuine alert. The header is trusted ONLY because the deployment
# declares the tunnel.

CLOUDFLARED_PEER = "127.0.0.1"
CF_HEADER = "CF-Connecting-IP"


def _tunnel_app(
    pg_session_factory: async_sessionmaker[AsyncSession],
    *,
    behind_tunnel: bool,
    peer_ip: str = CLOUDFLARED_PEER,
) -> ASGITransport:
    from strategy_manager.shared import db as shared_db

    get_settings().behind_cloudflare_tunnel = behind_tunnel
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    return ASGITransport(app=app, client=(peer_ip, 12345))


@pytest.fixture(autouse=True)
def _reset_tunnel_flag() -> AsyncIterator[None]:
    yield
    get_settings().behind_cloudflare_tunnel = False


async def test_behind_the_tunnel_a_forwarded_tradingview_address_is_accepted(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    transport = _tunnel_app(pg_session_factory, behind_tunnel=True)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/tradingview",
            params={"secret": SECRET},
            json=VALID_PAYLOAD,
            headers={CF_HEADER: ALLOWED_IP},
        )

    assert response.status_code == 200


async def test_behind_the_tunnel_a_forwarded_stranger_is_rejected(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    transport = _tunnel_app(pg_session_factory, behind_tunnel=True)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/tradingview",
            params={"secret": SECRET},
            json=VALID_PAYLOAD,
            headers={CF_HEADER: DISALLOWED_IP},
        )

    assert response.status_code == 401

    async with pg_session_factory() as session:
        jobs = (await session.execute(select(JobRow))).scalars().all()
    assert jobs == []


async def test_behind_the_tunnel_a_missing_header_is_rejected(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No fallback to the peer address, which is the loopback."""
    transport = _tunnel_app(pg_session_factory, behind_tunnel=True)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/tradingview", params={"secret": SECRET}, json=VALID_PAYLOAD
        )

    assert response.status_code == 401


async def test_without_the_tunnel_declared_the_header_cannot_grant_access(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The whole reason the flag exists: a request that reaches the port
    directly must not be able to name its own source address."""
    transport = _tunnel_app(
        pg_session_factory, behind_tunnel=False, peer_ip=DISALLOWED_IP
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/tradingview",
            params={"secret": SECRET},
            json=VALID_PAYLOAD,
            headers={CF_HEADER: ALLOWED_IP},
        )

    assert response.status_code == 401

    async with pg_session_factory() as session:
        jobs = (await session.execute(select(JobRow))).scalars().all()
    assert jobs == []

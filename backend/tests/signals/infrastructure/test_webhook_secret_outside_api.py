"""The two routes outside the ``/api`` sweep never answer the webhook secret.

``test_webhook_secret_router.py`` sweeps every ``/api`` route. ``/health`` and
``POST /webhook/tradingview`` are mounted elsewhere, so the sweep never asked
them; until now only a reading of their code said they keep the value out (S2).

The webhook is the route that RECEIVES the secret (in its query string), so it
is the one most likely to echo it: it is asked once with the right secret and
an alert it accepts, once with a wrong secret, and once with the right secret
and an alert it refuses. Each answer is inspected whole, headers included.
"""

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_strategy,
)
from tests.owner import secret_hash

pytestmark = pytest.mark.integration

ALLOWED_IP = "52.89.214.238"
SECRET = "wh-s3cret-4c0de9a1-must-never-leak"
WEBHOOK = "/webhook/tradingview"


def _alert(strategy_id: UUID, *, symbol: str = "STXUSDT.P") -> dict[str, object]:
    return {
        "data": {"action": "buy", "contracts": "10", "position_size": "10"},
        "price": "0.5",
        "signal_param": "{}",
        "signal_type": str(strategy_id),
        "symbol": symbol,
        "time": "2026-10-02T10:15:30Z",
    }


@pytest.fixture(autouse=True)
def _configure_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "webhook_secret", SECRET)


@pytest.fixture
async def client(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with pg_session_factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    transport = ASGITransport(app=app, client=(ALLOWED_IP, 12345), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as api:
        yield api


def _assert_secret_free(response: Response, what: str) -> None:
    assert SECRET not in response.text, f"{what} put the secret in its body"
    for name, value in response.headers.items():
        assert SECRET not in name and SECRET not in value, (
            f"{what} put the secret in the {name} header"
        )


async def test_health_never_answers_the_secret(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert set(response.json()) == {"status", "dry_run"}
    _assert_secret_free(response, "GET /health")


async def test_an_accepted_alert_is_answered_without_the_secret(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET webhook_secret_hash = :hash WHERE id = :id"),
            {"hash": secret_hash(SECRET), "id": strategy_id},
        )
        await session.commit()

    response = await client.post(WEBHOOK, params={"secret": SECRET}, json=_alert(strategy_id))

    assert response.status_code == 200
    assert response.json()["accepted"] is True
    _assert_secret_free(response, "an accepted webhook alert")


async def test_a_wrong_secret_is_refused_without_either_secret(client: AsyncClient) -> None:
    wrong = "not-the-secret-0f3a"

    response = await client.post(WEBHOOK, params={"secret": wrong}, json=_alert(uuid4()))

    assert response.status_code == 401
    _assert_secret_free(response, "a webhook alert with a wrong secret")
    assert wrong not in response.text, "the refusal echoed the secret the sender provided"


async def test_a_refused_alert_is_answered_without_the_secret(
    client: AsyncClient,
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    # The alert's shape is judged after its strategy's secret, so it needs one.
    strategy_id = uuid4()
    await seed_strategy(pg_session_factory, strategy_id=strategy_id)
    async with pg_session_factory() as session:
        await session.execute(
            text("UPDATE strategies SET webhook_secret_hash = :hash WHERE id = :id"),
            {"hash": secret_hash(SECRET), "id": strategy_id},
        )
        await session.commit()

    refused = await client.post(
        WEBHOOK, params={"secret": SECRET}, json=_alert(strategy_id, symbol="")
    )
    not_json = await client.post(
        WEBHOOK,
        params={"secret": SECRET},
        content=b"not json at all",
        headers={"Content-Type": "application/json"},
    )

    assert refused.status_code == 422
    assert not_json.status_code == 422
    _assert_secret_free(refused, "a refused webhook alert")
    _assert_secret_free(not_json, "a webhook alert that is not JSON")

"""``DELETE /api/me``: a user deletes their own account (openspec/changes/
account-deletion, S2-S5).

Mounted through ``create_app()`` with a real PostgreSQL session. The one who
deletes is the user ``OTHER_HEADERS`` signs in as; the fixture owner authors the
strategy they hold a seat on elsewhere, and a third user subscribes to theirs.
The symbols are spelled as in production: the alert ``STXUSDT.P``, the ledger
``STXUSDT``.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.models import ExchangeCredentialRow
from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from strategy_manager.shared.config import get_settings
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.identity_auth import OTHER_EMAIL, OTHER_HEADERS, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
    seed_signal,
)
from tests.owner import OWNER_ID, ensure_pool, secret_hash, seed_reservation_row, seed_user
from tests.subscriptions.infrastructure.seeds import (
    MARKET,
    open_allocation,
    strategy,
    subscription,
    user,
)

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]
WAIT_SECONDS = 5.0
LOGGER = "strategy_manager.identity.application.delete_account"
GARBAGE = b"\x00not-a-real-ciphertext\xff"


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


@pytest.fixture(autouse=True)
def _brake_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "dry_run", False)


@pytest.fixture
async def factory(pg_session_factory: Factory) -> Factory:  # noqa: F811
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE users CASCADE"))
        await session.commit()
    return pg_session_factory


@pytest.fixture
async def client(factory: Factory) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api


class Account:
    """The user who deletes, and everything around them."""

    def __init__(self, factory: Factory) -> None:
        self.factory = factory
        self.id: UUID = uuid4()
        self.pool_id = 0
        self.strategy_id: UUID = uuid4()
        self.elsewhere_id: UUID = uuid4()
        self.subscriber_id: UUID = uuid4()
        self.subscriber_pool_id = 0

    async def build(self) -> "Account":
        async with self.factory() as session:
            await seed_user(session, OTHER_EMAIL, self.id)
            await session.execute(
                text("UPDATE users SET display_name = 'Deleting user' WHERE id = :id"),
                {"id": self.id},
            )
            self.pool_id = await ensure_pool(session, MARKET, user_id=self.id)
            await ensure_pool(session, ("binance", "usdt-m", "USDT"), user_id=self.id)
            await session.commit()
        await self.key("bybit")
        # A superseded key keeps its sealed columns until the account goes.
        await self.key("bybit", active=False)
        # Their own strategy, with their seat and a subscriber's.
        self.strategy_id = await strategy(self.factory, author_id=self.id, named=False)
        await subscription(self.factory, self.id, self.strategy_id, self.pool_id)
        self.subscriber_id, subscriber_pool = await user(self.factory)
        assert subscriber_pool is not None
        self.subscriber_pool_id = subscriber_pool
        await subscription(self.factory, self.subscriber_id, self.strategy_id, subscriber_pool)
        # Their seat on the fixture owner's strategy.
        self.elsewhere_id = await strategy(self.factory, named=False)
        await subscription(self.factory, self.id, self.elsewhere_id, self.pool_id)
        return self

    async def key(self, exchange: str, *, active: bool = True) -> None:
        async with self.factory() as session:
            session.add(
                ExchangeCredentialRow(
                    user_id=self.id,
                    exchange=exchange,
                    label="default",
                    is_active=active,
                    wrapped_dek=GARBAGE,
                    dek_nonce=GARBAGE,
                    api_key_ciphertext=GARBAGE,
                    api_key_nonce=GARBAGE,
                    api_secret_ciphertext=GARBAGE,
                    api_secret_nonce=GARBAGE,
                    api_key_last4="abcd",
                    trade_capable=True,
                    trade_capability_source="VERIFIED",
                    withdraw_check="VERIFIED",
                    validated_at=datetime(2026, 10, 1, tzinfo=UTC),
                    internal_transfer=None,
                )
            )
            await session.commit()

    async def one(self, sql: str, **params: Any) -> Any:
        async with self.factory() as session:
            return (await session.execute(text(sql), params)).one()

    async def rows(self, sql: str, **params: Any) -> list[tuple[Any, ...]]:
        async with self.factory() as session:
            return [tuple(row) for row in (await session.execute(text(sql), params)).all()]

    async def snapshot(self) -> dict[str, object]:
        """Everything a refused deletion must leave as it was."""
        return {
            "user": await self.rows(
                "SELECT email, display_name, deleted_at FROM users WHERE id = :id", id=self.id
            ),
            "keys": await self.rows(
                "SELECT id, is_active FROM exchange_credentials WHERE user_id = :id ORDER BY id",
                id=self.id,
            ),
            "pools": await self.rows(
                "SELECT id, enabled FROM capital_pools ORDER BY id",
            ),
            "strategies": await self.rows(
                "SELECT id, enabled, visibility, archived_at, webhook_secret_hash "
                "FROM strategies ORDER BY id"
            ),
            "seats": await self.rows("SELECT id, status FROM subscriptions ORDER BY id"),
        }


async def test_a_user_holding_nothing_is_anonymised_and_everything_of_theirs_is_closed(
    client: AsyncClient, factory: Factory
) -> None:
    account = await Account(factory).build()

    response = await client.delete("/api/me", headers=OTHER_HEADERS)

    assert response.status_code == 204, response.text
    email, name, deleted_at = await account.one(
        "SELECT email, display_name, deleted_at FROM users WHERE id = :id", id=account.id
    )
    assert (email, name) == (f"deleted-{account.id}@invalid", None)
    assert deleted_at is not None
    # Every key row is gone, the inactive one and its ciphertext included.
    assert (
        await account.rows("SELECT id FROM exchange_credentials WHERE user_id = :id", id=account.id)
        == []
    )
    assert await account.rows(
        "SELECT enabled FROM capital_pools WHERE user_id = :id", id=account.id
    ) == [(False,), (False,)]
    # Their strategy: private, stopped, archived, and its old secret no longer matches.
    enabled, visibility, share_token, archived_at, secret = await account.one(
        "SELECT enabled, visibility, share_token, archived_at, webhook_secret_hash "
        "FROM strategies WHERE id = :id",
        id=account.strategy_id,
    )
    assert (enabled, visibility, share_token) == (False, "PRIVATE", None)
    assert archived_at is not None
    assert secret != secret_hash("fixture-secret")
    assert await account.rows(
        "SELECT enabled FROM strategy_enablement_events WHERE strategy_id = :id",
        id=account.strategy_id,
    ) == [(False,)]
    # Every seat on it ended, the author's and the subscriber's, and their seat elsewhere.
    assert await account.rows(
        "SELECT status FROM subscriptions WHERE strategy_id = :id", id=account.strategy_id
    ) == [("ENDED",), ("ENDED",)]
    assert await account.rows(
        "SELECT status, ended_at IS NOT NULL FROM subscriptions WHERE strategy_id = :id",
        id=account.elsewhere_id,
    ) == [("ENDED", True)]


async def test_nobody_elses_account_is_touched(client: AsyncClient, factory: Factory) -> None:
    account = await Account(factory).build()
    owner_seat = await subscription(
        factory, OWNER_ID, account.elsewhere_id, await _owner_pool(factory)
    )

    response = await client.delete("/api/me", headers=OTHER_HEADERS)

    assert response.status_code == 204, response.text
    # The other author's strategy runs on, and its author's seat with it.
    assert await account.rows(
        "SELECT enabled, archived_at FROM strategies WHERE id = :id", id=account.elsewhere_id
    ) == [(True, None)]
    assert await account.rows("SELECT status FROM subscriptions WHERE id = :id", id=owner_seat) == [
        ("ACTIVE",)
    ]
    # The subscriber keeps their pool and their name; only the seat on the deleted
    # author's strategy ended.
    assert await account.rows(
        "SELECT enabled FROM capital_pools WHERE id = :id", id=account.subscriber_pool_id
    ) == [(True,)]
    assert await account.rows(
        "SELECT deleted_at FROM users WHERE id IN (:a, :b)", a=account.subscriber_id, b=OWNER_ID
    ) == [(None,), (None,)]


async def test_their_own_position_refuses_naming_it_and_changes_nothing(
    client: AsyncClient, factory: Factory
) -> None:
    account = await Account(factory).build()
    await open_allocation(factory, account.id, account.elsewhere_id)
    before = await account.snapshot()

    response = await client.delete("/api/me", headers=OTHER_HEADERS)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "error": "ACCOUNT_HOLDS_POSITIONS",
        "message": "The account cannot be deleted while a position is open.",
        "symbols": ["STXUSDT"],
        "strategies": [],
    }
    assert await account.snapshot() == before


async def test_a_subscribers_position_on_their_strategy_refuses_naming_the_strategy(
    client: AsyncClient, factory: Factory
) -> None:
    account = await Account(factory).build()
    await open_allocation(factory, account.subscriber_id, account.strategy_id)
    before = await account.snapshot()

    response = await client.delete("/api/me", headers=OTHER_HEADERS)

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["symbols"] == []
    assert detail["strategies"] == [
        {
            "id": str(account.strategy_id),
            "name": f"strategy-{account.strategy_id}",
            "symbols": ["STXUSDT"],
        }
    ]
    assert await account.snapshot() == before


async def test_signing_in_again_with_the_same_e_mail_makes_a_new_empty_user(
    client: AsyncClient, factory: Factory
) -> None:
    account = await Account(factory).build()
    assert (await client.delete("/api/me", headers=OTHER_HEADERS)).status_code == 204

    me = await client.get("/api/me", headers=OTHER_HEADERS)

    assert me.status_code == 200
    assert me.json()["email"] == OTHER_EMAIL
    assert me.json()["display_name"] is None
    (new_id,) = await account.one("SELECT id FROM users WHERE email = :e", e=OTHER_EMAIL)
    assert new_id != account.id
    assert await account.rows("SELECT id FROM capital_pools WHERE user_id = :id", id=new_id) == []


async def test_the_log_names_the_user_id_and_never_the_e_mail(
    client: AsyncClient, factory: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    account = await Account(factory).build()

    with caplog.at_level(logging.INFO, logger=LOGGER):
        assert (await client.delete("/api/me", headers=OTHER_HEADERS)).status_code == 204

    lines = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert len(lines) == 1
    assert str(account.id) in lines[0]
    assert OTHER_EMAIL not in caplog.text


async def test_the_deletion_waits_for_an_opening_in_flight_and_then_refuses_on_it(
    client: AsyncClient, factory: Factory
) -> None:
    """S4: an opening holds the user's pool lock while it reserves. The deletion
    waits for it, then sees the reservation it committed."""
    account = await Account(factory).build()
    opening = factory()
    try:
        await PoolLockAdapter(opening).acquire(account.id, *MARKET)
        signal_id = uuid4()
        await seed_signal(
            factory,
            signal_id=signal_id,
            strategy_id=account.elsewhere_id,
            idempotency_key=f"key-{signal_id}",
        )
        await seed_reservation_row(
            opening,
            reservation_id=uuid4(),
            strategy_id=account.elsewhere_id,
            signal_id=signal_id,
            market=MARKET,
            status="PENDING",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            user_id=account.id,
            mode="LIVE",
        )

        deletion = asyncio.create_task(client.delete("/api/me", headers=OTHER_HEADERS))
        await _until_waiting_on_an_advisory_lock(factory)
        assert not deletion.done()

        await opening.commit()
    finally:
        await opening.close()

    response = await asyncio.wait_for(deletion, WAIT_SECONDS)
    assert response.status_code == 409, response.text
    # The signal's own spelling, BTCUSDT: the seeds' default.
    assert response.json()["detail"]["symbols"] == ["BTCUSDT"]


async def test_no_identity_is_401(client: AsyncClient) -> None:
    assert (await client.delete("/api/me")).status_code == 401


async def _owner_pool(factory: Factory) -> int:
    async with factory() as session:
        pool_id = await ensure_pool(session, MARKET, user_id=OWNER_ID)
        await session.commit()
    return pool_id


async def _until_waiting_on_an_advisory_lock(factory: Factory) -> None:
    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    while True:
        async with factory() as session:
            waiting = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
                    )
                )
            ).scalar_one()
        if waiting:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the deletion never waited on a pool lock")
        await asyncio.sleep(0.02)

"""Who ``GET /api/strategies/{id}/share-preview`` answers (tasks.md F.6), on real
PostgreSQL. The subscribe step and a subscriber's share read it, so it reaches past
the author: to anyone who may subscribe, and to anyone who holds a subscription.

The market a preview reads is on the public page already, and every figure comes from
the signed-in user's own pool. Without such a pool a non-author is simply not there
yet: a 404 with no ERROR line, since any signed-in user can ask, and an ERROR reaches
the operator's Telegram.
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.main import create_app
from strategy_manager.shared import db as shared_db
from tests.identity_auth import ADMIN_HEADERS, act_as, sign_in_as_admin
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)
from tests.owner import seed_snapshot
from tests.subscriptions.infrastructure import seeds

pytestmark = pytest.mark.integration

Factory = async_sessionmaker[AsyncSession]

T0 = datetime(2026, 9, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _signed_in(monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in_as_admin(monkeypatch)


async def _preview(factory: Factory, user_id: UUID, strategy_id: UUID) -> Response:
    app = create_app()
    act_as(app, user_id)

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[shared_db.get_session] = _session
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=ADMIN_HEADERS
    ) as client:
        return await client.get(f"/api/strategies/{strategy_id}/share-preview")


async def _user_with_balance(factory: Factory, total: str) -> tuple[UUID, int]:
    user_id, pool = await seeds.user(factory)
    assert pool is not None
    async with factory() as session:
        await seed_snapshot(
            session,
            seeds.MARKET,
            total=Decimal(total),
            available=Decimal(total),
            observed_at=T0,
            user_id=user_id,
        )
        await session.commit()
    return user_id, pool


async def _private(factory: Factory, strategy_id: UUID) -> None:
    async with factory() as session:
        await session.execute(
            text("UPDATE strategies SET visibility = 'PRIVATE' WHERE id = :id"),
            {"id": strategy_id},
        )
        await session.commit()


async def test_a_stranger_reads_a_public_strategy_against_their_own_pool(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    stranger, _ = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)

    response = await _preview(pg_session_factory, stranger, strategy_id)

    assert response.status_code == 200, response.text
    assert Decimal(response.json()["balance"]["total"]) == Decimal("200")


async def test_a_stranger_never_reads_a_private_strategy(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    stranger, _ = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(
        pg_session_factory, visibility="PRIVATE", author_id=author
    )

    response = await _preview(pg_session_factory, stranger, strategy_id)

    assert response.status_code == 404


async def test_a_stranger_never_reads_an_archived_strategy(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    stranger, _ = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(pg_session_factory, archived=True, author_id=author)

    response = await _preview(pg_session_factory, stranger, strategy_id)

    assert response.status_code == 404


async def test_a_stranger_never_reads_a_strategy_whose_author_has_no_name(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    """The public page answers 404 for it, and the preview follows the page (G.2)."""
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    stranger, _ = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author, named=False)

    response = await _preview(pg_session_factory, stranger, strategy_id)

    assert response.status_code == 404


async def test_an_author_with_no_name_keeps_reading_their_own_strategy(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author, named=False)

    response = await _preview(pg_session_factory, author, strategy_id)

    assert response.status_code == 200, response.text


async def test_a_holder_keeps_reading_a_strategy_whose_author_has_no_name(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    holder, pool = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author, named=False)
    await seeds.subscription(pg_session_factory, holder, strategy_id, pool)

    response = await _preview(pg_session_factory, holder, strategy_id)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("status", ["ACTIVE", "LEAVING"])
async def test_a_subscriber_keeps_reading_a_strategy_that_turned_private(
    pg_session_factory: Factory,  # noqa: F811
    status: str,
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    subscriber, pool = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool, status=status)
    await _private(pg_session_factory, strategy_id)

    response = await _preview(pg_session_factory, subscriber, strategy_id)

    assert response.status_code == 200, response.text


async def test_a_subscriber_who_left_a_private_strategy_reads_it_no_more(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    subscriber, pool = await _user_with_balance(pg_session_factory, "200")
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)
    await seeds.subscription(pg_session_factory, subscriber, strategy_id, pool, status="ENDED")
    await _private(pg_session_factory, strategy_id)

    response = await _preview(pg_session_factory, subscriber, strategy_id)

    assert response.status_code == 404


async def test_a_stranger_with_no_pool_there_is_a_404_and_no_error_line(
    pg_session_factory: Factory,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    author, _ = await _user_with_balance(pg_session_factory, "1000")
    stranger, _ = await seeds.user(pg_session_factory, pool=False)
    strategy_id = await seeds.strategy(pg_session_factory, author_id=author)

    with caplog.at_level(logging.ERROR):
        response = await _preview(pg_session_factory, stranger, strategy_id)

    assert response.status_code == 404
    assert [record for record in caplog.records if record.levelno >= logging.ERROR] == []


async def test_an_unknown_strategy_stays_a_404(
    pg_session_factory: Factory,  # noqa: F811
) -> None:
    stranger, _ = await _user_with_balance(pg_session_factory, "200")

    response = await _preview(pg_session_factory, stranger, uuid4())

    assert response.status_code == 404

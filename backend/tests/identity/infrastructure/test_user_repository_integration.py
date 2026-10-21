"""``SqlAlchemyUserRepository`` against real PostgreSQL (multi-user design AD1;
tasks.md A.5).

The race this file exists for: the panel fires several requests at once on its
first load, so a brand-new user's first two requests can both find no row. Both
must end with ONE user. The second insert waits on the first's uncommitted entry
in ``ux_users_email``; the test proves it waits (``not task.done()`` while the
first transaction is held open, with the wait visible in ``pg_locks``), then that
it returns the first one's row instead of failing or making a second.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.identity.infrastructure.user_repository import SqlAlchemyUserRepository
from tests.ledger.infrastructure.conftest import (  # noqa: F401
    pg_engine,
    pg_session_factory,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def factory(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> async_sessionmaker[AsyncSession]:
    async with pg_session_factory() as session:
        await session.execute(text("TRUNCATE users"))
        await session.commit()
    return pg_session_factory


async def _count(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        return int((await session.execute(text("SELECT count(*) FROM users"))).scalar_one())


async def _until(condition: Callable[[], Awaitable[bool]], what: str) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while not await condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.02)


async def test_a_first_request_creates_the_user_with_now_as_both_timestamps(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        user = await SqlAlchemyUserRepository(session).find_or_create("new@example.com", T0)
        await session.commit()

    assert user.email == "new@example.com"
    assert user.created_at == T0
    assert user.last_seen_at == T0
    assert await _count(factory) == 1


async def test_a_later_request_returns_the_same_user_unchanged(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        first = await SqlAlchemyUserRepository(session).find_or_create("owner@example.com", T0)
        await session.commit()

    async with factory() as session:
        again = await SqlAlchemyUserRepository(session).find_or_create(
            "owner@example.com", T0 + timedelta(hours=1)
        )
        await session.commit()

    assert again == first
    assert await _count(factory) == 1


async def test_mark_seen_moves_only_that_users_last_seen(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        repo = SqlAlchemyUserRepository(session)
        owner = await repo.find_or_create("owner@example.com", T0)
        other = await repo.find_or_create("other@example.com", T0)
        await repo.mark_seen(owner.id, T0 + timedelta(minutes=5))
        await session.commit()

    async with factory() as session:
        repo = SqlAlchemyUserRepository(session)
        owner_now = await repo.find_or_create("owner@example.com", T0 + timedelta(hours=1))
        other_now = await repo.find_or_create("other@example.com", T0 + timedelta(hours=1))

    assert owner_now.last_seen_at == T0 + timedelta(minutes=5)
    assert owner_now.created_at == T0
    assert other_now == other


async def test_two_concurrent_first_requests_make_one_user(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def waiting_on_a_transaction() -> bool:
        async with factory() as probe:
            found = await probe.execute(
                text(
                    "SELECT count(*) FROM pg_locks "
                    "WHERE locktype = 'transactionid' AND NOT granted"
                )
            )
            return int(found.scalar_one()) >= 1

    async def second_request() -> object:
        async with factory() as session:
            user = await SqlAlchemyUserRepository(session).find_or_create(
                "race@example.com", T0 + timedelta(seconds=1)
            )
            await session.commit()
            return user

    async with factory() as holder:
        first = await SqlAlchemyUserRepository(holder).find_or_create("race@example.com", T0)
        task = asyncio.create_task(second_request())
        await _until(waiting_on_a_transaction, "the second insert to wait on the first")
        assert not task.done()
        await holder.commit()

    second = await task

    assert second == first
    assert await _count(factory) == 1

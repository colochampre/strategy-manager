"""The pool advisory lock identifies ONE USER's pool (multi-user tasks.md B.4).

Two users on the same ``(exchange, venue, settlement_currency)`` hold different
money, so they must not serialize against each other; the same user on the same
market must. Proven on real PostgreSQL with the lock-hold harness: one session
holds the lock and a second actor either waits (``not task.done()``) or
completes.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.infrastructure.advisory_lock import PgAdvisoryLockAdapter
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from tests.owner import OWNER_ID

pytestmark = pytest.mark.integration

_WAIT = 0.5
SECOND_USER = UUID("00000000-0000-4000-8000-0000000000b2")
_MARKET = PoolKey(exchange=Exchange.BYBIT, venue=Venue.USDT_M, settlement_currency=Currency.USDT)


async def _second_actor(
    factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> tuple[bool, asyncio.Task[None]]:
    """Starts an actor that takes the pool lock for ``user_id`` through the
    strategies adapter (a different code path, and a different spelling of the
    market: plain strings) and reports whether it finished within ``_WAIT``."""

    async def take() -> None:
        async with factory() as session:
            await PoolLockAdapter(session).acquire(user_id, "bybit", "usdt-m", "USDT")
            await session.rollback()

    task = asyncio.create_task(take())
    await asyncio.wait({task}, timeout=_WAIT)
    return task.done(), task


async def test_the_same_user_on_the_same_market_waits_for_the_held_lock(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(OWNER_ID, _MARKET))
        task: asyncio.Task[None] | None = None
        try:
            done, task = await _second_actor(pg_session_factory, OWNER_ID)
            assert not done, "the same user's pool lock did not wait for the holder"
        finally:
            await holder.rollback()
            if task is not None:
                await asyncio.wait({task}, timeout=5)
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        assert task.done()
        task.result()


async def test_another_user_on_the_same_market_does_not_wait(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(OWNER_ID, _MARKET))
        task: asyncio.Task[None] | None = None
        try:
            done, task = await _second_actor(pg_session_factory, SECOND_USER)
            assert done, "another user's pool waited for a lock that is not theirs"
            task.result()
        finally:
            await holder.rollback()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_the_lock_key_of_a_random_third_user_is_also_independent(
    pg_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Not just the fixed second user: any other id is a different lock."""
    async with pg_session_factory() as holder:
        await PgAdvisoryLockAdapter(holder).acquire(LockKey.from_pool_key(OWNER_ID, _MARKET))
        task: asyncio.Task[None] | None = None
        try:
            done, task = await _second_actor(pg_session_factory, uuid4())
            assert done, "a third user waited for the owner's pool lock"
            task.result()
        finally:
            await holder.rollback()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

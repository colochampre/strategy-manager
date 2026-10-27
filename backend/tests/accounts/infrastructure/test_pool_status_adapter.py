"""``SqlAlchemyPoolStatus``: whether ``user_id``'s pool on a market is disabled
(multi-user design AD8; tasks.md B.3).

The allocation path asks it inside the pool lock. Two users may each hold a pool
on the same market, and only the asking user's flag may answer: another user's
disabled pool must never skip this user's signal, nor another user's enabled
pool let a disabled one through.
"""

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from strategy_manager.accounts.infrastructure.pool_status_adapter import SqlAlchemyPoolStatus
from tests.ledger.infrastructure.conftest import pg_engine, pg_session_factory  # noqa: F401
from tests.owner import OWNER_ID, seed_other_user, seed_pool

pytestmark = pytest.mark.integration

BYBIT = ("bybit", "usdt-m", "USDT")
UNSEEDED = ("binance", "usdt-m", "USDT")


async def _is_disabled(
    factory: async_sessionmaker[AsyncSession],
    market: tuple[str, str, str],
    user_id: UUID = OWNER_ID,
) -> bool:
    async with factory() as session:
        return await SqlAlchemyPoolStatus(session).is_disabled(user_id, *market)


async def _other_users_pool(
    factory: async_sessionmaker[AsyncSession], market: tuple[str, str, str], *, enabled: bool
) -> UUID:
    async with factory() as session:
        other = await seed_other_user(session)
        await seed_pool(session, market, user_id=other, enabled=enabled)
        await session.commit()
    return other


async def _set_owner_enabled(
    factory: async_sessionmaker[AsyncSession], market: tuple[str, str, str], enabled: bool
) -> None:
    exchange, venue, currency = market
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE capital_pools SET enabled = :enabled WHERE user_id = :user_id "
                "AND exchange = :exchange AND venue = :venue AND settlement_currency = :c"
            ),
            {
                "enabled": enabled,
                "user_id": OWNER_ID,
                "exchange": exchange,
                "venue": venue,
                "c": currency,
            },
        )
        await session.commit()


async def test_an_enabled_pool_is_not_disabled(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    assert await _is_disabled(pg_session_factory, BYBIT) is False


async def test_a_disabled_pool_is_disabled(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    await _set_owner_enabled(pg_session_factory, BYBIT, False)

    assert await _is_disabled(pg_session_factory, BYBIT) is True


async def test_a_market_with_no_pool_is_not_disabled(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """No row is not "disabled": the balance read owns that failure."""
    assert await _is_disabled(pg_session_factory, UNSEEDED) is False


# --- Two users, one market (multi-user design AD8) ----------------------------


async def test_another_users_disabled_pool_never_disables_this_users_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """The owner's bybit pool is enabled; a second user's pool on the same market
    is disabled. The owner's pool is not disabled."""
    await _other_users_pool(pg_session_factory, BYBIT, enabled=False)

    assert await _is_disabled(pg_session_factory, BYBIT) is False


async def test_another_users_enabled_pool_never_enables_this_users_disabled_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """The owner's bybit pool is disabled; a second user's pool on the same market
    is enabled. The owner's pool is still disabled."""
    await _set_owner_enabled(pg_session_factory, BYBIT, False)
    await _other_users_pool(pg_session_factory, BYBIT, enabled=True)

    assert await _is_disabled(pg_session_factory, BYBIT) is True


async def test_a_user_without_a_pool_is_not_answered_by_another_users_disabled_pool(
    pg_session_factory: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """The owner's bybit pool is disabled; the second user holds none on bybit.
    The second user's question finds no row of theirs: not disabled."""
    await _set_owner_enabled(pg_session_factory, BYBIT, False)
    async with pg_session_factory() as session:
        other = await seed_other_user(session)
        await session.commit()

    assert await _is_disabled(pg_session_factory, BYBIT, user_id=other) is False

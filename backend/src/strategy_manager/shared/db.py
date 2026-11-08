"""Database engine and session wiring.

The job queue and the allocation lock both live in PostgreSQL, so there is a
single connection pool and a single transaction boundary for both.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import Pool

from strategy_manager.shared.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every persistence model."""


_settings = get_settings()

@dataclass(frozen=True)
class PoolBounds:
    """A pool that never grows past ``size`` and waits ``timeout_seconds`` for a slot."""

    size: int
    timeout_seconds: float


def create_engine_for(
    database_url: str,
    *,
    poolclass: type[Pool] | None = None,
    bounds: PoolBounds | None = None,
) -> AsyncEngine:
    """The one way this process builds an engine, the migrations' included.

    ``hide_parameters`` keeps bound values (ciphertexts, wrapped keys, nonces)
    out of a ``DBAPIError``'s text, which the alert bridge sends to Telegram
    and a failed migration prints to the owner's terminal. ``poolclass`` lets
    the migrations hold no pool (``NullPool``); ``bounds`` gives a pool of a
    fixed size with no overflow.
    """
    if poolclass is not None:
        return create_async_engine(
            database_url, pool_pre_ping=True, hide_parameters=True, poolclass=poolclass
        )
    if bounds is not None:
        return create_async_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
            pool_size=bounds.size,
            max_overflow=0,
            pool_timeout=bounds.timeout_seconds,
        )
    return create_async_engine(database_url, pool_pre_ping=True, hide_parameters=True)


engine = create_engine_for(_settings.database_url)

session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session

"""Database engine and session wiring.

The job queue and the allocation lock both live in PostgreSQL, so there is a
single connection pool and a single transaction boundary for both.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from strategy_manager.shared.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for every persistence model."""


_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True)

session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session

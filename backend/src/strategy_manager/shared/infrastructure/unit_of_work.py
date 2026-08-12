"""SQLAlchemy implementation of ``UnitOfWorkPort``.

Owns one ``AsyncSession`` per ``async with`` block. Callers explicitly call
``commit()``; any exception raised inside the block rolls back before the
session is closed, so a use case never has to remember cleanup.
"""

from types import TracebackType

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class SqlAlchemyUnitOfWork:
    """Async-context-managed transaction boundary backed by SQLAlchemy."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self.session is not None
        if exc_type is not None:
            await self.session.rollback()
        await self.session.close()
        self.session = None

    async def commit(self) -> None:
        assert self.session is not None
        await self.session.commit()

    async def rollback(self) -> None:
        assert self.session is not None
        await self.session.rollback()

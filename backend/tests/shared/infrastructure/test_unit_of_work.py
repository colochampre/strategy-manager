"""Unit tests for the SQLAlchemy unit-of-work wrapper, using a mock session.

No database: verifies the context-manager protocol (open on enter, commit on
explicit call, rollback+close on exception) without needing PostgreSQL.
"""

from unittest.mock import AsyncMock

import pytest

from strategy_manager.shared.infrastructure.unit_of_work import SqlAlchemyUnitOfWork


async def test_commit_delegates_to_the_session() -> None:
    session = AsyncMock()
    session_factory = lambda: session  # noqa: E731

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.commit()

    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()
    session.rollback.assert_not_awaited()


async def test_exception_inside_the_block_rolls_back_and_closes() -> None:
    session = AsyncMock()
    session_factory = lambda: session  # noqa: E731

    with pytest.raises(RuntimeError):
        async with SqlAlchemyUnitOfWork(session_factory):
            raise RuntimeError("boom")

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
    session.commit.assert_not_awaited()

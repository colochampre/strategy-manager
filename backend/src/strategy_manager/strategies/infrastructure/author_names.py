"""Implements ``strategies.application.ports.AuthorNamesPort``."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.infrastructure.models import UserRow


class SqlAlchemyAuthorNames:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_display_name(self, user_id: UUID) -> bool:
        name = (
            await self._session.execute(
                select(UserRow.display_name).where(UserRow.id == user_id)
            )
        ).scalar_one_or_none()
        return name is not None

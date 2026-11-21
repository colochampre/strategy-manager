"""``SqlAlchemyAuthorStanding``: implements ``AuthorStandingPort`` against
``users.suspended_at`` (public-site LS9, PS.13 S4). A plain read."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.shared.domain.errors import InvariantViolation


class SqlAlchemyAuthorStanding:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_suspended(self, user_id: UUID) -> bool:
        row = (
            await self._session.execute(select(UserRow.suspended_at).where(UserRow.id == user_id))
        ).one_or_none()
        if row is None:
            # A strategy's author is a foreign key: no row means a broken database, and
            # reading it as "not suspended" would let the strategy open.
            raise InvariantViolation(
                f"author {str(user_id)[:8]} has no row; the strategy's standing is unknown"
            )
        return row[0] is not None

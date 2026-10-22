"""SQLAlchemy adapter for ``UserRepositoryPort`` (multi-user design AD1)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.models import UserRow


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_or_create(self, email: str, now: datetime) -> User:
        """Insert-then-read, never read-then-insert. A concurrent first request
        for the same address waits on this insert's entry in ``ux_users_email``
        and then does nothing; its read runs in a fresh READ COMMITTED snapshot
        and finds the committed row. Read-then-insert would let both miss and
        one of them fail on the unique index."""

        await self._session.execute(
            insert(UserRow)
            .values(id=uuid4(), email=email, created_at=now, last_seen_at=now)
            .on_conflict_do_nothing(index_elements=[UserRow.email])
        )
        row = (
            await self._session.execute(select(UserRow).where(UserRow.email == email))
        ).scalar_one()
        return _to_domain(row)

    async def mark_seen(self, user_id: UUID, now: datetime) -> None:
        await self._session.execute(
            update(UserRow).where(UserRow.id == user_id).values(last_seen_at=now)
        )


def _to_domain(row: UserRow) -> User:
    return User(
        id=row.id, email=row.email, created_at=row.created_at, last_seen_at=row.last_seen_at
    )

"""SQLAlchemy adapter for ``UserRepositoryPort`` (multi-user design AD1)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.application.ports import DisplayNameTakenError
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.shared.domain.mode import Mode

_NAME_INDEX = "ux_users_display_name_lower"


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

    async def lock_for_mode_change(self, user_id: UUID) -> None:
        await self._session.execute(
            select(UserRow.id).where(UserRow.id == user_id).with_for_update()
        )

    async def set_mode(self, user_id: UUID, mode: Mode) -> None:
        await self._session.execute(
            update(UserRow).where(UserRow.id == user_id).values(mode=mode.value)
        )

    async def everyone(self) -> list[User]:
        """Every user, by e-mail, in ONE statement: the admin's list (decision 8)."""
        result = await self._session.execute(select(UserRow).order_by(UserRow.email))
        return [_to_domain(row) for row in result.scalars().all()]

    async def set_display_name(self, user_id: UUID, name: str) -> None:
        """The unique index decides, not a read first: two users racing for one name
        would both read it free. Only that index: any other failure stays a defect."""
        try:
            await self._session.execute(
                update(UserRow).where(UserRow.id == user_id).values(display_name=name)
            )
        except IntegrityError as error:
            if getattr(error.orig.__cause__, "constraint_name", None) == _NAME_INDEX:  # type: ignore[union-attr]
                raise DisplayNameTakenError from error
            raise


def _to_domain(row: UserRow) -> User:
    return User(
        id=row.id,
        email=row.email,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        mode=Mode(row.mode),
        display_name=row.display_name,
    )

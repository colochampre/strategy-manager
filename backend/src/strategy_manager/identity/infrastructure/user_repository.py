"""SQLAlchemy adapter for ``UserRepositoryPort`` (multi-user design AD1)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.application.ports import DisplayNameTakenError
from strategy_manager.identity.domain.legal import LegalVersions
from strategy_manager.identity.domain.profile import Profile
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.models import LegalAcceptanceRow, UserRow
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

    async def wipe(self, user_id: UUID, now: datetime) -> None:
        """The row stops naming anyone (account-deletion S3): the e-mail becomes a
        placeholder no sign-in can match, which frees the real one, and the name
        goes. So does the identity given at sign-up, until LQ6 says it may stay
        (public-site LS5). ``ck_users_deleted_names_nobody`` holds them together."""
        await self._session.execute(
            update(UserRow)
            .where(UserRow.id == user_id)
            .values(
                email=f"deleted-{user_id}@invalid",
                display_name=None,
                deleted_at=now,
                first_name=None,
                last_name=None,
                cuit=None,
                country=None,
                adult_declared_at=None,
                truthful_declared_at=None,
            )
        )

    async def give(self, user_id: UUID, profile: Profile, declared_at: datetime) -> bool:
        """One conditional UPDATE: of two forms sent at once, the second waits on the
        first's row lock, then re-reads ``cuit`` as set and matches nothing."""
        result = await self._session.execute(
            update(UserRow)
            .where(UserRow.id == user_id, UserRow.cuit.is_(None))
            .values(
                first_name=profile.first_name,
                last_name=profile.last_name,
                cuit=profile.cuit,
                country=profile.country,
                adult_declared_at=declared_at,
                truthful_declared_at=declared_at,
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def correct_name(self, user_id: UUID, first_name: str, last_name: str) -> bool:
        """One conditional UPDATE: only a row that has a profile changes, so a name
        alone never starts one (``ck_users_profile_whole`` would refuse it anyway)."""
        result = await self._session.execute(
            update(UserRow)
            .where(UserRow.id == user_id, UserRow.cuit.is_not(None))
            .values(first_name=first_name, last_name=last_name)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def has_profile(self, user_id: UUID) -> bool:
        cuit = await self._session.scalar(select(UserRow.cuit).where(UserRow.id == user_id))
        return cuit is not None

    async def set_mode(self, user_id: UUID, mode: Mode) -> None:
        await self._session.execute(
            update(UserRow).where(UserRow.id == user_id).values(mode=mode.value)
        )

    async def everyone(self) -> list[User]:
        """Every user, by e-mail, in ONE statement: the admin's list (decision 8).
        A deleted account names nobody, so it is not listed (account-deletion S6)."""
        result = await self._session.execute(
            select(UserRow).where(UserRow.deleted_at.is_(None)).order_by(UserRow.email)
        )
        return [_to_domain(row) for row in result.scalars().all()]

    async def count_deleted(self) -> int:
        """How many accounts were deleted: the admin's list says so beside it."""
        result = await self._session.execute(
            select(func.count()).select_from(UserRow).where(UserRow.deleted_at.is_not(None))
        )
        return int(result.scalar_one())

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


class SqlAlchemyLegalAcceptances:
    """The acceptance record (migration 0046): appended to, never changed."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, user_id: UUID, versions: LegalVersions, accepted_at: datetime) -> None:
        self._session.add(
            LegalAcceptanceRow(
                id=uuid4(),
                user_id=user_id,
                terms_version=versions.terms,
                privacy_version=versions.privacy,
                accepted_at=accepted_at,
            )
        )
        await self._session.flush()

    async def latest(self, user_id: UUID) -> LegalVersions | None:
        row = (
            await self._session.execute(
                select(LegalAcceptanceRow.terms_version, LegalAcceptanceRow.privacy_version)
                .where(LegalAcceptanceRow.user_id == user_id)
                .order_by(LegalAcceptanceRow.accepted_at.desc(), LegalAcceptanceRow.id.desc())
                .limit(1)
            )
        ).one_or_none()
        return None if row is None else LegalVersions(terms=row[0], privacy=row[1])


def _to_domain(row: UserRow) -> User:
    profile = (
        None
        if row.cuit is None
        else Profile(
            first_name=row.first_name or "",
            last_name=row.last_name or "",
            cuit=row.cuit,
            country=row.country or "",
        )
    )
    return User(
        id=row.id,
        email=row.email,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        mode=Mode(row.mode),
        display_name=row.display_name,
        profile=profile,
    )

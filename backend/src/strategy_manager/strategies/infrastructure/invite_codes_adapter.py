"""Implements ``strategies.application.ports.InviteCodesPort`` on ``invite_codes``
(migration 0038). Flushes and never commits: the use case commits once."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.strategies.application.ports import ListedCode
from strategy_manager.subscriptions.infrastructure.models import InviteCodeRow


def _live(now: datetime) -> ColumnElement[bool]:
    """``IssuedCode.is_live`` in SQL: neither revoked nor redeemed, and not expired."""
    return and_(
        InviteCodeRow.revoked_at.is_(None),
        InviteCodeRow.redeemed_at.is_(None),
        InviteCodeRow.expires_at > now,
    )


class SqlAlchemyInviteCodes:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        code_id: UUID,
        strategy_id: UUID,
        code_hash: str,
        hint: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        self._session.add(
            InviteCodeRow(
                id=code_id,
                strategy_id=strategy_id,
                code_hash=code_hash,
                hint=hint,
                created_at=created_at,
                expires_at=expires_at,
            )
        )
        await self._session.flush()

    async def live(self, strategy_id: UUID, now: datetime) -> list[ListedCode]:
        rows = await self._session.execute(
            select(InviteCodeRow.id, InviteCodeRow.hint, InviteCodeRow.expires_at)
            .where(InviteCodeRow.strategy_id == strategy_id, _live(now))
            .order_by(InviteCodeRow.created_at, InviteCodeRow.id)
        )
        return [ListedCode(id=row.id, hint=row.hint, expires_at=row.expires_at) for row in rows]

    async def revoke_live(self, strategy_id: UUID, code_id: UUID, now: datetime) -> str | None:
        # One statement, so a code redeemed or revoked by another transaction since
        # it was listed is matched by nothing here rather than overwritten.
        hint = (
            await self._session.execute(
                update(InviteCodeRow)
                .where(
                    InviteCodeRow.id == code_id,
                    InviteCodeRow.strategy_id == strategy_id,
                    _live(now),
                )
                .values(revoked_at=now)
                .returning(InviteCodeRow.hint)
            )
        ).scalar_one_or_none()
        await self._session.flush()
        return hint

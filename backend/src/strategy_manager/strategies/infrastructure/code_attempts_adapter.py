"""Implements ``strategies.application.code_entry.CodeAttemptsPort`` on
``invite_codes`` and ``invite_code_attempts`` (migrations 0038 and 0039).

Given a session of its own (``get_code_check``), so its commit is not the request's.

**The lock** is ``pg_advisory_xact_lock`` in the two-key form the pool locks use,
with ``invite-code-attempts`` as its first key, which no ``exchange:venue`` spells,
and the user's id as its second. It is held only for the few statements of one check
and taken with no other lock held, so it cannot join a cycle with the pool lock.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.strategies.domain.invite_code import IssuedCode
from strategy_manager.subscriptions.infrastructure.models import (
    InviteCodeAttemptRow,
    InviteCodeRow,
)

LOCK_NAMESPACE = "invite-code-attempts"


class SqlAlchemyCodeAttempts:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def hold_attempts_of(self, user_id: UUID) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:namespace), hashtext(:user))"),
            {"namespace": LOCK_NAMESPACE, "user": str(user_id)},
        )

    async def failures_since(self, user_id: UUID, since: datetime) -> int:
        count = (
            await self._session.execute(
                select(func.count()).where(
                    InviteCodeAttemptRow.user_id == user_id,
                    InviteCodeAttemptRow.attempted_at > since,
                )
            )
        ).scalar_one()
        return int(count)

    async def find(self, strategy_id: UUID, code_hash: str) -> IssuedCode | None:
        row = (
            await self._session.execute(
                select(
                    InviteCodeRow.expires_at, InviteCodeRow.revoked_at, InviteCodeRow.redeemed_at
                ).where(
                    InviteCodeRow.strategy_id == strategy_id, InviteCodeRow.code_hash == code_hash
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return IssuedCode(
            expires_at=row.expires_at, revoked_at=row.revoked_at, redeemed_at=row.redeemed_at
        )

    async def locate(self, code_hash: str) -> tuple[UUID, IssuedCode] | None:
        """A hash is unique across every strategy (``ux_invite_codes_code_hash``)."""
        row = (
            await self._session.execute(
                select(
                    InviteCodeRow.strategy_id,
                    InviteCodeRow.expires_at,
                    InviteCodeRow.revoked_at,
                    InviteCodeRow.redeemed_at,
                ).where(InviteCodeRow.code_hash == code_hash)
            )
        ).one_or_none()
        if row is None:
            return None
        return row.strategy_id, IssuedCode(
            expires_at=row.expires_at, revoked_at=row.revoked_at, redeemed_at=row.redeemed_at
        )

    async def record_failure(self, user_id: UUID, at: datetime, prune_before: datetime) -> None:
        await self._session.execute(
            delete(InviteCodeAttemptRow).where(
                InviteCodeAttemptRow.user_id == user_id,
                InviteCodeAttemptRow.attempted_at <= prune_before,
            )
        )
        self._session.add(InviteCodeAttemptRow(user_id=user_id, attempted_at=at))
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

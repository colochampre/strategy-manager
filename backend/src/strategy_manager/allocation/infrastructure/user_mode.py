"""``SqlAlchemyUserMode``: implements ``UserModePort`` against ``users.mode``.

The user row is read ``FOR SHARE`` on the allocation's own session, after the pool
advisory lock (lock order: advisory lock first, then row locks). A change of the
user's mode takes the same row ``FOR UPDATE``, so the two cannot interleave: the
flip waits for this opening's transaction, or lands first and this reads the new
mode. ``FOR SHARE`` rather than ``FOR UPDATE`` so that openings of one user in
different pools do not queue on each other for a read.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.infrastructure.models import UserRow
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.mode import Mode, effective_mode


class SqlAlchemyUserMode:
    """``brake`` is ``.env``'s ``DRY_RUN``: a brake over everyone, applied on top
    of the user's own mode."""

    def __init__(self, session: AsyncSession, *, brake: bool) -> None:
        self._session = session
        self._brake = brake

    async def effective_mode(self, user_id: UUID) -> Mode:
        stored = (
            await self._session.execute(
                select(UserRow.mode).where(UserRow.id == user_id).with_for_update(read=True)
            )
        ).scalar_one_or_none()
        if stored is None:
            raise InvariantViolation(
                f"user {str(user_id)[:8]} has no row; an opening cannot take a mode from it"
            )
        return effective_mode(brake=self._brake, user_mode=Mode(stored))

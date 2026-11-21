"""The admin suspends an account, or lifts its suspension (openspec/changes/
public-site, LS9, PS.13 S1).

A suspended account opens nothing new while its closes keep running, and the
strategies it authored stop opening for every subscriber (S3, S4). This use case
only records the fact; what it stops is read where an opening is decided.

The user row is taken ``FOR UPDATE`` before the decision, as a mode change does: an
opening holds that row ``FOR SHARE`` until its reservation commits, so a
suspension waits for the one in flight and every later one sees it.

The admin cannot suspend themself: nobody would be left to lift it. Suspending
twice keeps the first date; lifting an account that is not suspended changes
nothing. An unknown or deleted account is refused.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from strategy_manager.identity.application.ports import CommitPort, SuspensionUsersPort


class SuspensionRefusal(StrEnum):
    CANNOT_SUSPEND_YOURSELF = "CANNOT_SUSPEND_YOURSELF"
    USER_NOT_FOUND = "USER_NOT_FOUND"


class SuspensionRefusedError(Exception):
    def __init__(self, refusal: SuspensionRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


class SuspendAccount:
    def __init__(self, users: SuspensionUsersPort, commit: CommitPort) -> None:
        self._users = users
        self._commit = commit

    async def execute(
        self, *, admin_id: UUID, user_id: UUID, suspended: bool, now: datetime
    ) -> None:
        if suspended and user_id == admin_id:
            raise SuspensionRefusedError(SuspensionRefusal.CANNOT_SUSPEND_YOURSELF)
        if not await self._users.lock_for_suspension(user_id):
            raise SuspensionRefusedError(SuspensionRefusal.USER_NOT_FOUND)
        if suspended:
            await self._users.suspend(user_id, now)
        else:
            await self._users.lift_suspension(user_id)
        await self._commit.commit()

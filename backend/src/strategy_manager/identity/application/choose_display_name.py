"""A user chooses the name other users know them by (multi-user decision 27).

A name can change and cannot be emptied: a public strategy rests on its author
having one, and that rule reads the name once, when the strategy turns public.
So "empty" is not a value here, and ``normalize_display_name`` refuses it.
"""

import logging
from uuid import UUID

from strategy_manager.identity.application.ports import CommitPort, UserRepositoryPort
from strategy_manager.identity.domain.display_name import normalize_display_name

logger = logging.getLogger(__name__)


class ChooseDisplayName:
    def __init__(self, users: UserRepositoryPort, commit: CommitPort) -> None:
        self._users = users
        self._commit = commit

    async def execute(self, user_id: UUID, raw: str) -> str:
        """Returns the name as stored. Raises ``InvalidDisplayNameError`` or
        ``DisplayNameTakenError``."""
        name = normalize_display_name(raw)
        await self._users.set_display_name(user_id, name)
        await self._commit.commit()
        logger.info("User %s chose a display name", user_id)
        return name

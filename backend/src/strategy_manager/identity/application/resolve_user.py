"""Resolve the verified e-mail into a user, creating them on their first request
(multi-user decisions 1 and 2; design AD1)."""

from dataclasses import replace
from datetime import timedelta

from strategy_manager.identity.application.ports import UserRepositoryPort
from strategy_manager.identity.domain.user import User, normalize_email
from strategy_manager.shared.application.ports import ClockPort

#: How stale ``last_seen_at`` may get before a request moves it. The admin's
#: users list (decision 8) reads it in minutes; writing it on every request
#: would turn every page load into a write.
LAST_SEEN_RESOLUTION = timedelta(minutes=1)


class ResolveUser:
    def __init__(self, users: UserRepositoryPort, clock: ClockPort) -> None:
        self._users = users
        self._clock = clock

    async def execute(self, email: str) -> User:
        """The user for ``email`` as the assertion carried it. Raises
        ``InvalidEmailError``, before touching the repository, when it is not
        an address."""

        normal = normalize_email(email)
        now = self._clock.now()
        user = await self._users.find_or_create(normal, now)
        if now - user.last_seen_at >= LAST_SEEN_RESOLUTION:
            await self._users.mark_seen(user.id, now)
            user = replace(user, last_seen_at=now)
        return user

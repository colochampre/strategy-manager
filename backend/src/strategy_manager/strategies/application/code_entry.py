"""``CheckInviteCode``: whether a code a user brings opens a strategy (multi-user
decision 41; tasks.md K.4).

Every reader route and subscribing ask this, and only when the strategy does not
open without the code, so a code is never read, nor counted, where it is not needed.

**One user's checks run one at a time.** The port holds a lock of the user's until
the commit, so two requests cannot both read a count under the limit before either
writes its failure: the limit is exact, not "about ten".

**What counts as a failure:** a code that is no code (malformed), one that no live or
dead code of this strategy has, and a dead one. A live code is not a failure. Each
failure is written, and the user's failures older than the window pruned, in the
same commit. A user at the limit has their code refused unread, and that refusal
writes nothing.

**Answers.** A live code returns the code, which subscribing spends. No such code
returns None, which every caller answers as the strategy that does not exist. A dead
one raises ``InviteCodeNotLive`` with its reason, which names nobody. The limit
raises ``TooManyCodeAttempts``.

**The port runs in its own transaction**, apart from the request's: a failure is
committed even when the request then answers a refusal and rolls back.

The log names the user, the strategy and the failures in the window, never the code.
"""

import logging
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.strategies.domain.invite_code import (
    ATTEMPT_WINDOW,
    InviteCode,
    InviteCodeNotLive,
    IssuedCode,
    TooManyCodeAttempts,
    may_attempt,
)

logger = logging.getLogger(__name__)


class CodeAttemptsPort(Protocol):
    async def hold_attempts_of(self, user_id: UUID) -> None:
        """Waits for, then holds until the commit, the lock of ``user_id``'s checks."""
        ...

    async def failures_since(self, user_id: UUID, since: datetime) -> int: ...

    async def find(self, strategy_id: UUID, code_hash: str) -> IssuedCode | None:
        """The code of ``strategy_id`` with this hash, live or dead, or None."""
        ...

    async def record_failure(self, user_id: UUID, at: datetime, prune_before: datetime) -> None:
        """Writes one failure of ``user_id`` and drops theirs older than ``prune_before``."""
        ...

    async def commit(self) -> None: ...


class CheckInviteCode:
    def __init__(self, attempts: CodeAttemptsPort, clock: ClockPort) -> None:
        self._attempts = attempts
        self._clock = clock

    async def check(self, user_id: UUID, strategy_id: UUID, typed: str) -> InviteCode | None:
        await self._attempts.hold_attempts_of(user_id)
        now = self._clock.now()
        failures = await self._attempts.failures_since(user_id, now - ATTEMPT_WINDOW)
        if not may_attempt(failures_in_window=failures):
            await self._attempts.commit()
            logger.warning(
                "invite code refused unread, too many failures: user=%s strategy=%s "
                "failures_last_hour=%d",
                user_id,
                strategy_id,
                failures,
            )
            raise TooManyCodeAttempts(
                "too many invitation codes were wrong in the last hour; try again later"
            )

        code = InviteCode.parse(typed)
        issued = None if code is None else await self._attempts.find(strategy_id, code.hash)
        reason = None if issued is None else issued.why_dead(now)
        if issued is not None and reason is None:
            await self._attempts.commit()
            return code

        await self._attempts.record_failure(user_id, now, now - ATTEMPT_WINDOW)
        await self._attempts.commit()
        logger.warning(
            "invite code failed: user=%s strategy=%s outcome=%s failures_last_hour=%d",
            user_id,
            strategy_id,
            "UNKNOWN" if reason is None else reason.value,
            failures + 1,
        )
        if reason is not None:
            raise InviteCodeNotLive(reason)
        return None

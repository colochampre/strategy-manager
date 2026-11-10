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

**A live code of a strategy that opens to nobody** -- archived, or its author has no
name (decision 27) -- is answered by ``locate`` as no code, as the page answers it,
so the lookup names no strategy the page then refuses (K.D advisory A2). It is a
real code, not a guess, so it is not counted, as the page does not count it.
"""

import logging
from dataclasses import dataclass
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
from strategy_manager.strategies.domain.strategy import Entry, Visibility, offered_to

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LocatedCode:
    """A code found by its hash alone, with what decides whether its strategy opens."""

    strategy_id: UUID
    issued: IssuedCode
    visibility: Visibility
    archived: bool
    author_named: bool

    @property
    def opens(self) -> bool:
        """Whether the page this code names would open to it: the page's own rule."""
        return not self.archived and offered_to(
            self.visibility, author_named=self.author_named, entry=Entry.CODE
        )


class CodeAttemptsPort(Protocol):
    async def hold_attempts_of(self, user_id: UUID) -> None:
        """Waits for, then holds until the commit, the lock of ``user_id``'s checks."""
        ...

    async def failures_since(self, user_id: UUID, since: datetime) -> int: ...

    async def find(self, strategy_id: UUID, code_hash: str) -> IssuedCode | None:
        """The code of ``strategy_id`` with this hash, live or dead, or None."""
        ...

    async def locate(self, code_hash: str) -> LocatedCode | None:
        """The code with this hash, of whichever strategy, and that strategy; or None."""
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
        """The live code of ``strategy_id`` the user typed, or None."""
        now, failures = await self._admit(user_id, strategy_id)
        code = InviteCode.parse(typed)
        issued = None if code is None else await self._attempts.find(strategy_id, code.hash)
        if await self._settle(user_id, strategy_id, issued, now=now, failures=failures):
            return code
        return None

    async def locate(self, user_id: UUID, typed: str) -> UUID | None:
        """The strategy a live code opens, for a reader who knows only the code (tasks.md
        K.6); None when no code has it. Counted exactly as ``check`` counts."""
        now, failures = await self._admit(user_id, None)
        code = InviteCode.parse(typed)
        found = None if code is None else await self._attempts.locate(code.hash)
        if found is not None and found.issued.why_dead(now) is None and not found.opens:
            await self._attempts.commit()
            logger.info(
                "invite code opens nothing, its strategy archived or its author unnamed: "
                "user=%s strategy=%s",
                user_id,
                found.strategy_id,
            )
            return None
        strategy_id, issued = (None, None) if found is None else (found.strategy_id, found.issued)
        if await self._settle(user_id, strategy_id, issued, now=now, failures=failures):
            return strategy_id
        return None

    async def _admit(self, user_id: UUID, strategy_id: UUID | None) -> tuple[datetime, int]:
        """Holds the user's lock and answers the instant and their failures in the
        window; past the limit, refuses unread and writes nothing."""
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
        return now, failures

    async def _settle(
        self,
        user_id: UUID,
        strategy_id: UUID | None,
        issued: IssuedCode | None,
        *,
        now: datetime,
        failures: int,
    ) -> bool:
        """True for a live code. Otherwise writes the failure, logs it, and raises
        ``InviteCodeNotLive`` for a dead code or answers False for none."""
        reason = None if issued is None else issued.why_dead(now)
        if issued is not None and reason is None:
            await self._attempts.commit()
            return True

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
        return False

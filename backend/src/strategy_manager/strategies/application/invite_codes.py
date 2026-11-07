"""An author's invitation codes to a strategy off the public list (multi-user
decision 41; tasks.md K.3).

**Issuing.** A code is made only for a PRIVATE strategy that is not archived and
whose author has a name: a code opens a page that names its author (decision 27),
and a PUBLIC or LINK strategy has no use for one. The strategy row is read ``FOR
UPDATE``, the lock ``UpdateStrategy`` takes, so a code is never made beside a
concurrent turn to PUBLIC. The code leaves in the return value once; the database
keeps its hash and its last four characters.

**Listing** answers only the live codes, with no code in them.

**Revoking** marks a live code revoked and keeps its row. A code that is not live,
or not this strategy's, is ``UnknownInviteCode``: there is nothing left to revoke.
Revoking takes no visibility and no archive check, because it only takes access
away.

**Another user's strategy is a strategy that does not exist** (AD8): the caller hands
in the author's own repository, so the answer is the same ``UnknownStrategy``.

The log names the strategy, the code's id and its hint, never the code or its hash.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import (
    AuthorHasNoDisplayName,
    AuthorNamesPort,
    CommitPort,
    InviteCodesPort,
    ListedCode,
    StrategyRepositoryPort,
)
from strategy_manager.strategies.application.update_strategy import (
    StrategyArchived,
    UnknownStrategy,
)
from strategy_manager.strategies.domain.invite_code import InviteCode, IssuedCode
from strategy_manager.strategies.domain.strategy import Strategy, Visibility

logger = logging.getLogger(__name__)


class StrategyNotPrivate(DomainError):
    """Codes are made only for a PRIVATE strategy: a PUBLIC one is on Explore, and a
    LINK one opens to its link."""


class UnknownInviteCode(DomainError):
    """No live code of this strategy has this id."""


@dataclass(frozen=True, slots=True)
class NewCode:
    """A code just made. ``code`` is shown once and never again; ``repr`` hides it."""

    id: UUID
    code: InviteCode = field(repr=False)
    expires_at: datetime


async def _authored(repository: StrategyRepositoryPort, strategy_id: UUID) -> Strategy:
    strategy = await repository.get_by_id(strategy_id)
    if strategy is None:
        raise UnknownStrategy(f"no strategy registered under id {strategy_id}")
    return strategy


class IssueInviteCode:
    def __init__(
        self,
        repository: StrategyRepositoryPort,
        codes: InviteCodesPort,
        author_names: AuthorNamesPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._repository = repository
        self._codes = codes
        self._author_names = author_names
        self._commit = commit
        self._clock = clock

    async def issue(self, strategy_id: UUID) -> NewCode:
        strategy = await self._repository.get_by_id_for_update(strategy_id)
        if strategy is None:
            raise UnknownStrategy(f"no strategy registered under id {strategy_id}")
        if strategy.archived_at is not None:
            raise StrategyArchived(
                f"strategy {strategy_id} ({strategy.name!r}) is archived "
                "and read-only; nothing about it may be edited"
            )
        if strategy.visibility is not Visibility.PRIVATE:
            raise StrategyNotPrivate(
                f"strategy {strategy_id} is {strategy.visibility.value}: invitation codes "
                "are made only for a PRIVATE strategy"
            )
        if not await self._author_names.has_display_name(strategy.author_id):
            raise AuthorHasNoDisplayName

        code = InviteCode.generate()
        created_at = self._clock.now()
        issued = IssuedCode.new(created_at)
        code_id = uuid4()
        await self._codes.add(
            code_id, strategy_id, code.hash, code.hint, created_at, issued.expires_at
        )
        await self._commit.commit()
        logger.info(
            "invite code issued: strategy=%s code_id=%s hint=%s", strategy_id, code_id, code.hint
        )
        return NewCode(id=code_id, code=code, expires_at=issued.expires_at)


class ListInviteCodes:
    def __init__(
        self, repository: StrategyRepositoryPort, codes: InviteCodesPort, clock: ClockPort
    ) -> None:
        self._repository = repository
        self._codes = codes
        self._clock = clock

    async def list(self, strategy_id: UUID) -> list[ListedCode]:
        await _authored(self._repository, strategy_id)
        return await self._codes.live(strategy_id, self._clock.now())


class RevokeInviteCode:
    def __init__(
        self,
        repository: StrategyRepositoryPort,
        codes: InviteCodesPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._repository = repository
        self._codes = codes
        self._commit = commit
        self._clock = clock

    async def revoke(self, strategy_id: UUID, code_id: UUID) -> None:
        await _authored(self._repository, strategy_id)
        hint = await self._codes.revoke_live(strategy_id, code_id, self._clock.now())
        if hint is None:
            raise UnknownInviteCode(f"no live invitation code {code_id} on strategy {strategy_id}")
        await self._commit.commit()
        logger.info(
            "invite code revoked: strategy=%s code_id=%s hint=%s", strategy_id, code_id, hint
        )

"""``UpdateStrategy``: changing a registered strategy, and the one change it
refuses to make.

**A strategy cannot be moved between capital pools.** ``venue`` and
``settlement_currency`` are fixed at registration and there is no way to edit
them here. That is not an omission — it is the guard.

Moving a strategy from one pool to another looks like an edit and is not. It
is a different pool of money, with a different balance, different minimums,
and — the part that costs — different open positions. A strategy holding a
long on spot that is switched to ``usdt-m`` would have its NEXT close routed
to the futures adapter: the close never reaches the position, the spot holding
stays open, and the system believes it closed. That is the same failure the
venue registry was built to prevent, arriving through the front door.

Checking "is a position open?" before allowing the move would be the obvious
alternative, and it is worse than it looks: the answer changes between the
check and the write, and a strategy that is flat right now may be mid-signal.
Refusing outright costs the owner one re-registration and removes the failure
entirely.

So: to trade the same idea on a different pool, register a second strategy.
Its id is the alert's ``signalType``, so this also forces the honest
conversation — you need a second alert, because one alert cannot mean two
different pools.

Everything that does NOT change where the money comes from is editable:
``name``, ``fill_mode``, ``enabled``, ``visibility`` and ``description``.

**The share is not editable here any more** (multi-user C.4b). It is each
subscriber's, changed through ``ChangeShare``. The strategy's own copy is written
once, at registration, and ``process_signal`` keeps sizing from it until C.6.
"""

import logging
from dataclasses import dataclass, replace
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import (
    AuthorHasNoDisplayName,
    AuthorNamesPort,
    CommitPort,
    EnablementLogPort,
    StrategyRepositoryPort,
)
from strategy_manager.strategies.domain.share_token import new_share_token
from strategy_manager.strategies.domain.stop_loss import StopLossPct
from strategy_manager.strategies.domain.strategy import (
    NEEDS_A_NAMED_AUTHOR,
    FillMode,
    Strategy,
    Visibility,
)

logger = logging.getLogger(__name__)


class Unchanged:
    """Says "leave it as it is" for a field whose None means something."""

    def __repr__(self) -> str:
        return "UNCHANGED"


UNCHANGED = Unchanged()


class UnknownStrategy(DomainError):
    """No strategy is registered under this id."""


class StrategyArchived(DomainError):
    """Archive is terminal (decision 14): once a strategy is archived, no
    PATCH and no allowed-pairs PUT may change it -- the ``terminal_at``
    precedent (design.md § 8, "Archived strategies are read-only"). This is
    stricter than merely refusing to re-enable one: EVERY field is frozen,
    so a client cannot rename or re-scope a retired strategy either."""


@dataclass(frozen=True, slots=True)
class UpdateCommand:
    """Every field except ``strategy_id`` is optional. ``None`` means "leave
    it as it is", so a caller changing one thing cannot silently reset the
    rest to defaults it never sent.
    """

    strategy_id: UUID
    name: str | None = None
    fill_mode: FillMode | None = None
    enabled: bool | None = None
    visibility: Visibility | None = None
    # The one field that can be emptied, so "leave it" is ``UNCHANGED`` and None
    # clears it. Otherwise in its stored shape (``description_of``).
    description: str | None | Unchanged = UNCHANGED
    # Applies to openings made after the change only (D5).
    stop_loss_pct: StopLossPct | None = None


class UpdateStrategy:
    """Edits the mutable half of a registered strategy.

    ``enablement_log``/``clock`` exist because ``enabled`` is not an
    ordinary field: every ACTUAL change to it must append exactly one event
    to the append-only enablement log, in the SAME transaction as the write
    (spec: strategy-lifecycle § "Enable/Disable Event Log"). Reading the
    strategy row through ``get_by_id_for_update`` (a ``SELECT ... FOR
    UPDATE``) rather than ``get_by_id`` is what makes "the same transaction"
    also mean "serialized against a concurrent toggle of the same row" —
    design.md § 9, tasks.md 2d.3.
    """

    def __init__(
        self,
        repository: StrategyRepositoryPort,
        commit: CommitPort,
        enablement_log: EnablementLogPort,
        clock: ClockPort,
        author_names: AuthorNamesPort,
    ) -> None:
        self._repository = repository
        self._commit = commit
        self._enablement_log = enablement_log
        self._clock = clock
        self._author_names = author_names

    async def update(self, command: UpdateCommand) -> Strategy:
        strategy = await self._repository.get_by_id_for_update(command.strategy_id)
        if strategy is None:
            raise UnknownStrategy(
                f"no strategy registered under id {command.strategy_id}"
            )
        if strategy.archived_at is not None:
            raise StrategyArchived(
                f"strategy {command.strategy_id} ({strategy.name!r}) is archived "
                "and read-only; nothing about it may be edited"
            )

        # On turning public or LINK, not on being so: a strategy made public before
        # names existed stays editable (decisions 27 and 41).
        turns_named = (
            command.visibility in NEEDS_A_NAMED_AUTHOR
            and command.visibility is not strategy.visibility
        )
        if turns_named and not await self._author_names.has_display_name(strategy.author_id):
            raise AuthorHasNoDisplayName

        policy = strategy.policy
        if command.fill_mode is not None:
            policy = replace(policy, fill_mode=command.fill_mode)

        updated = replace(
            strategy,
            name=strategy.name if command.name is None else command.name,
            policy=policy,
            enabled=strategy.enabled if command.enabled is None else command.enabled,
            # No leverage is touched: a seat left above the new cap has its openings
            # refused instead (``ProcessDelivery``), and its leverage stays as it was.
            stop_loss_pct=(
                strategy.stop_loss_pct if command.stop_loss_pct is None else command.stop_loss_pct
            ),
            description=(
                strategy.description
                if isinstance(command.description, Unchanged)
                else command.description
            ),
        )
        # Through ``with_visibility``, so the link's token is made, kept or dropped
        # with the change (decision 41).
        if command.visibility is not None:
            updated = updated.with_visibility(command.visibility, new_share_token)

        await self._repository.update(updated)

        # Only an ACTUAL change writes an event (spec: "A PATCH that does
        # not change the effective enabled value MUST write no event").
        # This append happens BEFORE commit, in the same session/
        # transaction as the row write above — if it raises, neither
        # persists (tasks.md 2d, atomicity requirement).
        if updated.enabled != strategy.enabled:
            await self._enablement_log.append(
                strategy.id, updated.enabled, self._clock.now()
            )

        await self._commit.commit()
        if updated.stop_loss_pct != strategy.stop_loss_pct:
            logger.info(
                "strategy stop level changed from %s to %s: strategy=%s author=%s",
                format(strategy.stop_loss_pct.value, "f"),
                format(updated.stop_loss_pct.value, "f"),
                updated.id,
                updated.author_id,
            )
        # Whoever holds a link opens the strategy, so when one began or stopped
        # working is answerable from the log, never the token itself; a link killed
        # and made again is how it rotates (K.D advisory A3).
        if (strategy.share_token is None) != (updated.share_token is None):
            logger.info(
                "strategy link %s: strategy=%s author=%s visibility=%s",
                "made" if updated.share_token is not None else "killed",
                updated.id,
                updated.author_id,
                updated.visibility.value,
            )
        return updated

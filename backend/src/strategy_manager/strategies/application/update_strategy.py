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
``name``, ``fill_mode``, ``allocation_percent``, and ``enabled``.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import (
    CommitPort,
    EnablementLogPort,
    StrategyRepositoryPort,
)
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    FillMode,
    Strategy,
)


class UnknownStrategy(DomainError):
    """No strategy is registered under this id."""


@dataclass(frozen=True, slots=True)
class UpdateCommand:
    """Every field except ``strategy_id`` is optional. ``None`` means "leave
    it as it is", so a caller changing one thing cannot silently reset the
    rest to defaults it never sent.
    """

    strategy_id: UUID
    name: str | None = None
    fill_mode: FillMode | None = None
    allocation_percent: Decimal | None = None
    enabled: bool | None = None


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
    ) -> None:
        self._repository = repository
        self._commit = commit
        self._enablement_log = enablement_log
        self._clock = clock

    async def update(self, command: UpdateCommand) -> Strategy:
        strategy = await self._repository.get_by_id_for_update(command.strategy_id)
        if strategy is None:
            raise UnknownStrategy(
                f"no strategy registered under id {command.strategy_id}"
            )

        policy = strategy.policy
        if command.fill_mode is not None:
            policy = replace(policy, fill_mode=command.fill_mode)
        if command.allocation_percent is not None:
            policy = replace(
                policy,
                allocation_percent=AllocationPercent(command.allocation_percent),
            )

        updated = replace(
            strategy,
            name=strategy.name if command.name is None else command.name,
            policy=policy,
            enabled=strategy.enabled if command.enabled is None else command.enabled,
        )

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
        return updated

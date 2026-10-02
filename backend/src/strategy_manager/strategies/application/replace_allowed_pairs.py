"""``ReplaceAllowedPairs``: replacing a strategy's entire allowed-pairs list
as a unit (``PUT``), normalized through ``market_key()`` (design.md § 6
"Allowed pairs: an array column, migration 0024", "Normalization"; spec:
strategy-lifecycle § "Allowed-Pairs List Per Strategy"; tasks.md 2e.2).

The list is replaced WHOLE, never merged or diffed -- the panel's PUT sends
the complete list it wants, and this use case's only job is to normalize
every entry through ``market_key()`` before validating and writing it. Two
entries that normalize to the same pair (``SOLUSDT.P`` and ``SOLUSDT_PERP``)
collapse into one, and an entry that normalizes to nothing (``.P`` alone)
is refused the same way an empty list is -- storing it would be a pair no
signal could ever match.

**Reads through ``get_by_id_for_update``, the SAME row lock
``UpdateStrategy`` takes** (owner correction, 2026-09-25). The repository's
``update()`` assigns every mutable field, ``enabled`` included -- so a plain
unlocked read here would let a concurrent ``PATCH enabled`` interleave: this
PUT reads a stale ``enabled``, then writes it straight back, silently
reverting the PATCH's change with no error the instant SQLAlchemy's
dirty-tracking optimization does not happen to skip that assignment.
Relying on that by accident is not acceptable for the field the append-only
enablement log exists to guard. Verified against real Postgres by
``tests/strategies/infrastructure/test_update_strategy_concurrency.py``'s
``test_replace_allowed_pairs_and_update_strategy_serialize_on_the_same_row_lock``.
"""

from dataclasses import dataclass, replace
from uuid import UUID

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.application.ports import (
    CommitPort,
    PairCatalogPort,
    StrategyRepositoryPort,
)
from strategy_manager.strategies.application.update_strategy import (
    StrategyArchived,
    UnknownStrategy,
)
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs, EmptyAllowedPairs
from strategy_manager.strategies.domain.strategy import Strategy


@dataclass(frozen=True, slots=True)
class ReplaceAllowedPairsCommand:
    strategy_id: UUID
    pairs: list[str]


class ReplaceAllowedPairs:
    def __init__(
        self,
        repository: StrategyRepositoryPort,
        pairs: PairCatalogPort,
        commit: CommitPort,
    ) -> None:
        self._repository = repository
        self._pairs = pairs
        self._commit = commit

    async def replace(self, command: ReplaceAllowedPairsCommand) -> Strategy:
        strategy = await self._repository.get_by_id_for_update(command.strategy_id)
        if strategy is None:
            raise UnknownStrategy(
                f"no strategy registered under id {command.strategy_id}"
            )
        if strategy.archived_at is not None:
            raise StrategyArchived(
                f"strategy {command.strategy_id} ({strategy.name!r}) is archived "
                "and read-only; its allowed pairs cannot be replaced"
            )

        normalized = {market_key(pair) for pair in command.pairs}
        try:
            allowed_pairs = AllowedPairs(frozenset(normalized))
        except InvariantViolation as exc:
            raise EmptyAllowedPairs(str(exc)) from exc
        if not allowed_pairs.pairs:
            raise EmptyAllowedPairs(
                "allowed_pairs must contain at least one pair"
            )

        updated = replace(strategy, allowed_pairs=allowed_pairs)
        await self._repository.update(updated)
        await self._commit.commit()
        return updated

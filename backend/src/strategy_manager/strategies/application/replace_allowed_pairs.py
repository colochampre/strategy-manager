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

**The venue is asked BEFORE that lock, never under it** (decision 41, design
addendum § E). The request reads the strategy unlocked, works out which pairs it
would ADD, asks the catalogue only if there are any, then takes the row lock and
re-checks. A venue read can take ten seconds, and the same lock serializes the
``enabled`` toggle. Only added pairs are validated, so a pair the venue has since
delisted may be kept or removed (decision 15), and a pure removal works while the
venue is down. If another request changed the list between the two reads so that a
pair nobody validated would now be an addition, the save is refused
(``PairsChangedConcurrently``) rather than stored unchecked.
"""

import logging
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
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
    PairsChangedConcurrently,
    UnknownPairs,
    unknown_pairs,
)
from strategy_manager.strategies.domain.strategy import Strategy

logger = logging.getLogger(__name__)


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
        # Unlocked read: it decides what must be validated, and no venue call may
        # run while the row lock is held (design addendum § E).
        unlocked = self._require_editable(
            command, await self._repository.get_by_id(command.strategy_id)
        )

        allowed_pairs = self._normalize(command.pairs)

        # Decision 41: only pairs being ADDED are validated. A pair already stored
        # is never looked up, so a pair the venue has since delisted may be kept
        # or removed (decision 15). A replace that adds nothing never asks.
        candidates = allowed_pairs.pairs - unlocked.allowed_pairs.pairs
        if candidates:
            await self._assert_listed(unlocked, candidates)

        strategy = self._require_editable(
            command, await self._repository.get_by_id_for_update(command.strategy_id)
        )

        # The list may have changed between the two reads. A pair that is an
        # addition NOW but was not a candidate was never validated, and nothing is
        # stored unvalidated. The opposite drift (a candidate that is no longer an
        # addition) is harmless: it was checked anyway.
        if not allowed_pairs.pairs - strategy.allowed_pairs.pairs <= candidates:
            logger.warning(
                "pairs replace refused, the stored list changed during the request: "
                "strategy=%s pool=%s",
                command.strategy_id,
                _pool_label(strategy),
            )
            raise PairsChangedConcurrently(
                f"the allowed pairs of strategy {command.strategy_id} changed while "
                "this request was being checked; review the list and save again"
            )

        updated = replace(strategy, allowed_pairs=allowed_pairs)
        await self._repository.update(updated)
        await self._commit.commit()
        return updated

    @staticmethod
    def _require_editable(
        command: ReplaceAllowedPairsCommand, strategy: Strategy | None
    ) -> Strategy:
        if strategy is None:
            raise UnknownStrategy(f"no strategy registered under id {command.strategy_id}")
        if strategy.archived_at is not None:
            raise StrategyArchived(
                f"strategy {command.strategy_id} ({strategy.name!r}) is archived "
                "and read-only; its allowed pairs cannot be replaced"
            )
        return strategy

    @staticmethod
    def _normalize(pairs: list[str]) -> AllowedPairs:
        normalized = {market_key(pair) for pair in pairs}
        try:
            allowed_pairs = AllowedPairs(frozenset(normalized))
        except InvariantViolation as exc:
            raise EmptyAllowedPairs(str(exc)) from exc
        if not allowed_pairs.pairs:
            raise EmptyAllowedPairs("allowed_pairs must contain at least one pair")
        return allowed_pairs

    async def _assert_listed(self, strategy: Strategy, candidates: frozenset[str]) -> None:
        """Fail closed: an unreadable catalogue or a pool with none stores nothing."""
        pool = (
            strategy.policy.exchange.value,
            strategy.policy.venue.value,
            strategy.policy.settlement_currency.value,
        )
        label = _pool_label(strategy)
        try:
            available = await self._pairs.available_pairs(pool)
        except PairCatalogNotServed:
            logger.warning(
                "pairs replace refused, no pair catalogue for the pool: strategy=%s pool=%s",
                strategy.id,
                label,
            )
            raise
        except PairCatalogUnavailable:
            # The adapter already logged the venue failure; this line says what it cost.
            logger.warning(
                "pairs replace refused, pair catalogue unavailable: strategy=%s pool=%s",
                strategy.id,
                label,
            )
            raise
        unknown = unknown_pairs(candidates, available)
        if unknown:
            logger.warning(
                "pairs replace refused, the venue does not list the added pairs: "
                "strategy=%s pool=%s symbols=%.300r",
                strategy.id,
                label,
                list(unknown),
            )
            raise UnknownPairs(unknown)


def _pool_label(strategy: Strategy) -> str:
    policy = strategy.policy
    return f"{policy.exchange.value}/{policy.venue.value}/{policy.settlement_currency.value}"

"""``DeleteStrategy``: removing a strategy that has no history (owner decision 42;
design.md addendum 9x, § D and § I; tasks.md 9xc).

``ArchiveStrategy``'s sibling. A strategy the owner registered by mistake or as a
test has nothing worth keeping, and archiving it would keep its name and its id
forever. A strategy that ever acted (a signal, a reservation, an execution attempt,
a ledger entry, a booking proposal) cannot be removed without breaking a record, so
it is refused and archiving stays the only path. Enablement events are NOT history
(owner decision 42, Q1): migration 0028 deletes them with their strategy.

**The sequence, in order:**

1. An UNLOCKED read of the strategy row: it answers the 404 and gives the pool. A
   strategy's pool is immutable, so reading it before any lock is safe.
2. The pool's advisory lock -- the SAME key ``AllocateCapital`` takes (``PoolLockPort``).
3. ``SELECT ... FOR UPDATE`` on the strategy row, re-read fresh. Everything decided
   below comes from THIS read. A row that is gone was deleted by a concurrent
   request: 404.
4. Still enabled? Refused (``StillEnabled``) before any history is read.
5. Archived? Nothing to decide (owner decision 42, Q3): an archived strategy is
   disabled by construction and the history alone decides. It is never un-archived.
6. The history, read inside both locks. Any non-zero BLOCKING count refuses
   (``StrategyHasHistory``); the enablement events never do. Then the events are read,
   while they still exist, for the INFO line.
7. The ``DELETE``. A foreign-key refusal here means the count missed something: it is
   logged at ERROR naming the constraint and answered as ``StrategyHasHistory``.
8. Commit, releasing both locks, then one INFO line. The events went with the strategy
   (the foreign key cascades), so that line is the only record of how many there were,
   when the strategy was first enabled and for how long it ran.

**Lock order: the pool advisory lock, then the row lock -- never the other way
round**, as ``ArchiveStrategy`` documents (a reachable deadlock against a concurrent
``AllocateCapital`` otherwise). While this use case waits for the advisory lock it
holds no row lock, so it never makes the webhook wait behind an allocation. No venue
call and no other external call happens at any point.

**What serializes the delete against the webhook.** Ingress takes no advisory lock
and must not. The signal ``INSERT`` takes ``FOR KEY SHARE`` on the strategy row
through ``fk_signals_strategy``, which conflicts with step 3's ``FOR UPDATE``: an
ingest in flight makes the delete wait, then count one signal; a delete in flight
makes the ``INSERT`` wait, then fail on the foreign key (``UnknownSignalStrategy``).

**Logging** (design.md § I): one line per refusal (WARNING), one for the delete
(INFO) and one for the database backstop (ERROR, on purpose: the alert bridge
forwards ERROR records, and a hole in the check is a defect the owner must see).
No line carries a token, a credential or a payload. The name is logged with ``%r``.
"""

import logging
from dataclasses import fields
from typing import NoReturn
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.archive_strategy import StillEnabled
from strategy_manager.strategies.application.ports import (
    CommitPort,
    EnablementReaderPort,
    PoolLockPort,
    StrategyHistory,
    StrategyHistoryPort,
    StrategyRepositoryPort,
    StrategyStillReferenced,
)
from strategy_manager.strategies.application.update_strategy import UnknownStrategy
from strategy_manager.strategies.domain.enablement import uptime

logger = logging.getLogger(__name__)


class StrategyHasHistory(DomainError):
    """Something still references the strategy, so it can only be archived.

    ``history`` carries all six counts as READ. ``constraint`` is ``None`` when the
    count refused it, and the violated constraint's name when the database refused
    a delete the count had allowed (an incomplete check: see the ERROR line)."""

    def __init__(
        self, message: str, history: StrategyHistory, constraint: str | None = None
    ) -> None:
        super().__init__(message)
        self.history = history
        self.constraint = constraint


class DeleteStrategy:
    def __init__(
        self,
        repository: StrategyRepositoryPort,
        pool_lock: PoolLockPort,
        history: StrategyHistoryPort,
        enablement_log: EnablementReaderPort,
        clock: ClockPort,
        commit: CommitPort,
    ) -> None:
        self._repository = repository
        self._pool_lock = pool_lock
        self._history = history
        self._enablement_log = enablement_log
        self._clock = clock
        self._commit = commit

    async def delete(self, strategy_id: UUID) -> None:
        # Step 1: unlocked read -- the 404 and the pool, before any lock.
        unlocked = await self._repository.get_by_id(strategy_id)
        if unlocked is None:
            self._refuse_unknown(strategy_id)

        pool = (
            unlocked.policy.exchange.value,
            unlocked.policy.venue.value,
            unlocked.policy.settlement_currency.value,
        )

        # Step 2: the pool's advisory lock FIRST, then the row lock (see the
        # module docstring, "Lock order").
        await self._pool_lock.acquire(*pool)

        # Step 3: the row lock, second, and a fresh read: everything below is
        # decided from it, never from the unlocked read.
        strategy = await self._repository.get_by_id_for_update(strategy_id)
        if strategy is None:
            self._refuse_unknown(strategy_id)

        # Step 4: refused in the application, before any history is read.
        if strategy.enabled:
            logger.warning(
                "strategy delete refused, still enabled: id=%s name=%r",
                strategy_id,
                strategy.name,
            )
            raise StillEnabled(
                f"strategy {strategy_id} ({strategy.name!r}) is still enabled; "
                "disable it first (PATCH enabled=false), then delete it"
            )

        # Step 5: nothing to decide for an archived strategy (decision 42, Q3).

        # Step 6: the history, inside both locks. Under READ COMMITTED each count
        # is a new statement, so it sees what committed while the locks were awaited.
        history = await self._history.history(strategy_id)
        if not history.is_empty():
            counts = " ".join(f"{kind}={count}" for kind, count in _six(history))
            logger.warning(
                "strategy delete refused, it has history: id=%s name=%r %s",
                strategy_id,
                strategy.name,
                counts,
            )
            raise StrategyHasHistory(
                f"strategy {strategy_id} ({strategy.name!r}) has history "
                f"({counts}), so it cannot be deleted; archive it instead",
                history,
            )

        # The events are about to go with the strategy: read them now, for the INFO line.
        enablement = uptime(await self._enablement_log.list_for(strategy_id), self._clock.now())

        # Step 7: the delete. The database is the backstop for an incomplete count.
        try:
            await self._repository.delete(strategy_id)
        except StrategyStillReferenced as error:
            logger.error(
                "strategy delete refused by the database although every count was zero: "
                "id=%s name=%r constraint=%s; the history check is incomplete, extend "
                "StrategyHistory",
                strategy_id,
                strategy.name,
                error.constraint,
            )
            raise StrategyHasHistory(
                f"strategy {strategy_id} ({strategy.name!r}) is still referenced "
                f"through {error.constraint}, so it cannot be deleted; archive it instead",
                history,
                error.constraint,
            ) from error

        # Step 8: commit releases both locks. The INFO line is the only record
        # that the strategy ever existed.
        await self._commit.commit()
        logger.info(
            "strategy deleted: id=%s name=%r pool=%s/%s/%s archived=%s "
            "enablement_events=%d first_enabled_at=%s uptime_seconds=%d",
            strategy_id,
            strategy.name,
            *pool,
            strategy.archived_at is not None,
            history.enablement_events,
            enablement.first_enabled_at.isoformat() if enablement.first_enabled_at else "never",
            round(enablement.seconds),
        )

    @staticmethod
    def _refuse_unknown(strategy_id: UUID) -> NoReturn:
        logger.warning("strategy delete refused, unknown id: %s", strategy_id)
        raise UnknownStrategy(f"no strategy registered under id {strategy_id}")


def _six(history: StrategyHistory) -> list[tuple[str, int]]:
    """Every kind and its count, zero or not, in the fixed order of the fields."""
    return [(field.name, getattr(history, field.name)) for field in fields(history)]

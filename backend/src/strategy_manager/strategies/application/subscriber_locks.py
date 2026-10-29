"""The pool locks archive and delete take for EVERY subscriber of a strategy
(multi-user tasks.md C.9, finding e).

A strategy is one object for every user, and a subscriber's opening is worked in
that subscriber's own pool, under that pool's advisory lock. Archiving or deleting
the strategy therefore has to wait for each of those locks, or a subscriber's
opening in another pool would run unserialized against it.

**The sequence** (both callers follow it, lock order being the pool advisory lock
first and row locks after, everywhere):

1. ``acquire`` reads the pool of every ACTIVE or LEAVING subscription, UNLOCKED,
   then takes their advisory locks in ascending ``pool_id`` order. Two callers
   whose sets overlap therefore meet at the lowest shared pool and cannot wait on
   each other in a cycle.
2. The caller takes the strategy row lock.
3. ``confirm`` reads the set again, now under the row lock. A subscription needs a
   ``FOR KEY SHARE`` on the strategy row to be inserted (``fk_subscriptions_strategy``),
   which the caller's ``FOR UPDATE`` conflicts with: an insert in flight made the row
   lock wait until it committed, and one arriving later waits for the caller. So
   the second read sees every subscriber that will ever be seen, and any pool in it
   that step 1 did not lock is a subscriber who joined between the read and the
   locks. Locking it now would break the ascending order, so the caller is refused
   with ``SubscribersChanged`` and nothing has been written; trying again reads the
   larger set. A subscriber who LEFT in the meantime only leaves a lock held that is
   no longer needed, which is harmless.

A live subscription always has its pool row (``fk_subscriptions_pool`` has no
``ON DELETE``, so the database refuses to delete a pool one still names), which is
why the set cannot contain a pool that does not exist.
"""

import logging
from collections.abc import Iterable
from uuid import UUID

from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import (
    PoolLockPort,
    StrategySubscribersPort,
    SubscriberPool,
)

logger = logging.getLogger(__name__)


class SubscribersChanged(DomainError):
    """A subscriber joined the strategy between the read of its subscribers and the
    locks on their pools, so the locks taken do not cover everyone. Nothing was
    written; the caller asks again."""


class SubscriberLocks:
    def __init__(self, subscribers: StrategySubscribersPort, pool_lock: PoolLockPort) -> None:
        self._subscribers = subscribers
        self._pool_lock = pool_lock

    async def acquire(self, strategy_id: UUID) -> frozenset[int]:
        """Takes the advisory lock of every live subscriber's pool, lowest
        ``pool_id`` first, and returns the ids it locked."""
        pools = _ascending(await self._subscribers.live_pools(strategy_id))
        for pool in pools:
            await self._pool_lock.acquire(pool.user_id, *pool.pool)
        return frozenset(pool.pool_id for pool in pools)

    async def confirm(
        self, strategy_id: UUID, locked: frozenset[int], *, action: str
    ) -> list[SubscriberPool]:
        """The subscribers as they are NOW, under the row lock. Raises
        ``SubscribersChanged`` when one lives in a pool ``acquire`` did not lock."""
        now = _ascending(await self._subscribers.live_pools(strategy_id))
        joined = [pool.pool_id for pool in now if pool.pool_id not in locked]
        if joined:
            logger.warning(
                "strategy %s refused, a subscriber joined while its pool locks were taken: "
                "strategy=%s locked_pools=%s new_pools=%s",
                action,
                strategy_id,
                sorted(locked),
                joined,
            )
            raise SubscribersChanged(
                f"strategy {strategy_id} gained a subscriber while it was being {action}d; "
                "try again"
            )
        return now


def _ascending(pools: Iterable[SubscriberPool]) -> list[SubscriberPool]:
    """One entry per pool, lowest ``pool_id`` first."""
    return sorted({pool.pool_id: pool for pool in pools}.values(), key=lambda p: p.pool_id)

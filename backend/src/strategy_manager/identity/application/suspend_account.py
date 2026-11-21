"""The admin suspends an account, or lifts its suspension (openspec/changes/
public-site, LS9, PS.13 S1).

A suspended account opens nothing new while its closes keep running, and the
strategies it authored stop opening for every subscriber (S3, S4). This use case
records the fact; what it stops is read where an opening is decided.

**The sequence when suspending**, in one transaction, lock order being the pool
advisory locks first and row locks after, as everywhere:

1. Read, unlocked, the strategies the account authors and the pool of every live
   seat on them.
2. Take the advisory lock of each of those pools, lowest ``pool_id`` first, the order
   ``SubscriberLocks`` and ``DeleteAccount`` use, so this and an archive or a deletion
   whose pools overlap meet at the lowest shared pool and cannot wait on each other.
   An opening in flight holds its subscriber's pool lock, so this waits for it, and
   the next opening waits for this.
3. Take the user row ``FOR UPDATE``, as a mode change does: an opening holds that row
   ``FOR SHARE`` until its reservation commits, so a suspension waits for the one in
   flight and every later one sees it.
4. Read the sets again, locking each authored strategy row (a seat inserted on it
   needs that row ``FOR KEY SHARE``). A strategy or a seat in a pool not locked
   appeared in between: locking it now would break the order, so the suspension is
   refused with ``ACCOUNT_CHANGED`` and nothing is written; trying again reads the
   larger sets.
5. Record the date and commit once, releasing every lock.

Lifting takes the row alone: nothing it restores needs a fence, and nothing it stopped
is replayed.

The admin cannot suspend themself: nobody would be left to lift it. Suspending
twice keeps the first date; lifting an account that is not suspended changes
nothing. An unknown or deleted account is refused.
"""

import logging
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from strategy_manager.identity.application.ports import (
    AccountPoolLockPort,
    CommitPort,
    LockedPool,
    SuspensionFencePort,
    SuspensionUsersPort,
)

logger = logging.getLogger(__name__)


class SuspensionRefusal(StrEnum):
    CANNOT_SUSPEND_YOURSELF = "CANNOT_SUSPEND_YOURSELF"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    ACCOUNT_CHANGED = "ACCOUNT_CHANGED"


class SuspensionRefusedError(Exception):
    def __init__(self, refusal: SuspensionRefusal) -> None:
        super().__init__(refusal.value)
        self.refusal = refusal


class SuspendAccount:
    def __init__(
        self,
        users: SuspensionUsersPort,
        fence: SuspensionFencePort,
        pool_lock: AccountPoolLockPort,
        commit: CommitPort,
    ) -> None:
        self._users = users
        self._fence = fence
        self._pool_lock = pool_lock
        self._commit = commit

    async def execute(
        self, *, admin_id: UUID, user_id: UUID, suspended: bool, now: datetime
    ) -> None:
        if suspended and user_id == admin_id:
            raise SuspensionRefusedError(SuspensionRefusal.CANNOT_SUSPEND_YOURSELF)
        locked: frozenset[int] = frozenset()
        strategies: list[UUID] = []
        if suspended:
            # Steps 1 and 2: every pool a subscriber of the account's strategies opens
            # in, locked once, ascending, BEFORE the user row.
            strategies = [strategy.id for strategy in await self._fence.authored(user_id)]
            pools = await self._every_pool(strategies)
            for pool in pools:
                await self._pool_lock.acquire(
                    pool.user_id, pool.exchange, pool.venue, pool.currency
                )
            locked = frozenset(pool.pool_id for pool in pools)
        # Step 3.
        if not await self._users.lock_for_suspension(user_id):
            raise SuspensionRefusedError(SuspensionRefusal.USER_NOT_FOUND)
        if suspended:
            await self._confirm(user_id, strategies, locked)
            await self._users.suspend(user_id, now)
        else:
            await self._users.lift_suspension(user_id)
        await self._commit.commit()

    async def _every_pool(self, strategies: Iterable[UUID]) -> list[LockedPool]:
        pools: dict[int, LockedPool] = {}
        for strategy_id in strategies:
            for pool in await self._fence.subscriber_pools(strategy_id):
                pools[pool.pool_id] = pool
        return sorted(pools.values(), key=lambda pool: pool.pool_id)

    async def _confirm(self, user_id: UUID, strategies: list[UUID], locked: frozenset[int]) -> None:
        """Step 4: the sets as they are NOW, under the user row."""
        now_authored = {strategy.id for strategy in await self._fence.authored(user_id)}
        new_strategies = sorted(now_authored - set(strategies))
        new_pools: set[int] = set()
        for strategy_id in strategies:
            await self._fence.lock(strategy_id)
            new_pools.update(
                pool.pool_id
                for pool in await self._fence.subscriber_pools(strategy_id)
                if pool.pool_id not in locked
            )
        if new_strategies or new_pools:
            logger.warning(
                "account suspension refused, the account changed while its locks were taken: "
                "user=%s new_strategies=%s new_pools=%s",
                user_id,
                [str(strategy_id) for strategy_id in new_strategies],
                sorted(new_pools),
            )
            raise SuspensionRefusedError(SuspensionRefusal.ACCOUNT_CHANGED)

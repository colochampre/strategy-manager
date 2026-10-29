"""``Leave``: a user steps out of a strategy (owner decision 4).

**The sequence, in order** (lock order is the pool's advisory lock first, then
row locks, everywhere):

1. An UNLOCKED, user-scoped read of the subscription, to learn its strategy and
   so the pool whose lock to take. Another user's row is "not found" here, and
   only here. A strategy's market is immutable, so reading it unlocked is safe.
   The strategy's own author is refused here, before any lock (owner decision 22).
2. The user's pool advisory lock, the SAME one ``AllocateCapital`` takes: while
   it is held no opening of this user's can reserve capital, so the allocation
   read below cannot be outrun by one.
3. The subscription row ``FOR UPDATE``, re-read fresh. Everything decided below
   comes from THIS read.
4. Not ACTIVE: refused. An open allocation of the strategy for this user:
   LEAVING (no new openings; the position runs until the strategy closes it).
   None: ENDED.
5. Commit, releasing both locks.
"""

from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.subscriptions.application.errors import (
    AuthorCannotLeave,
    SubscriptionNotActive,
    SubscriptionNotFound,
)
from strategy_manager.subscriptions.application.ports import (
    CommitPort,
    OpenAllocationPort,
    PoolLockPort,
    StrategyLookupPort,
    SubscriptionRepositoryPort,
)
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus


class Leave:
    def __init__(
        self,
        subscriptions: SubscriptionRepositoryPort,
        strategies: StrategyLookupPort,
        allocations: OpenAllocationPort,
        pool_lock: PoolLockPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._subscriptions = subscriptions
        self._strategies = strategies
        self._allocations = allocations
        self._pool_lock = pool_lock
        self._commit = commit
        self._clock = clock

    async def leave(self, user_id: UUID, subscription_id: UUID) -> Subscription:
        unlocked = await self._subscriptions.get(user_id, subscription_id)
        if unlocked is None:
            raise SubscriptionNotFound(f"no subscription {subscription_id}")
        strategy = await self._strategies.find(unlocked.strategy_id)
        if strategy is None:
            raise SubscriptionNotFound(f"no subscription {subscription_id}")
        # A strategy's author is immutable, so the unlocked read decides it.
        if strategy.author_id == user_id:
            raise AuthorCannotLeave(
                f"the author of strategy {strategy.id} cannot leave it; disable or archive it"
            )

        await self._pool_lock.acquire(user_id, *strategy.market)

        subscription = await self._subscriptions.get_for_update(user_id, subscription_id)
        if subscription is None:
            raise SubscriptionNotFound(f"no subscription {subscription_id}")
        if subscription.status is not SubscriptionStatus.ACTIVE:
            raise SubscriptionNotActive(
                f"subscription {subscription_id} is {subscription.status}, not ACTIVE"
            )

        now = self._clock.now()
        if await self._allocations.holds_open_allocation(
            user_id, subscription.strategy_id, strategy.market
        ):
            left = subscription.leave(now)
        else:
            left = subscription.end(now)
        await self._subscriptions.update(left)
        await self._commit.commit()
        return left

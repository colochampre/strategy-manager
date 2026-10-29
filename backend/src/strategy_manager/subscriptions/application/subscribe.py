"""``Subscribe``: a user takes a place in a strategy, in their own pool."""

from uuid import UUID, uuid4

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.strategies.domain.strategy import AllocationPercent, Visibility
from strategy_manager.subscriptions.application.errors import (
    AlreadySubscribed,
    NoPoolForMarket,
    StrategyArchived,
    StrategyNotFound,
)
from strategy_manager.subscriptions.application.ports import (
    CommitPort,
    StrategyLookupPort,
    SubscriptionRepositoryPort,
    UserPoolPort,
)
from strategy_manager.subscriptions.domain.subscription import Subscription


class Subscribe:
    def __init__(
        self,
        subscriptions: SubscriptionRepositoryPort,
        strategies: StrategyLookupPort,
        pools: UserPoolPort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._subscriptions = subscriptions
        self._strategies = strategies
        self._pools = pools
        self._commit = commit
        self._clock = clock

    async def subscribe(
        self, user_id: UUID, strategy_id: UUID, allocation_percent: AllocationPercent
    ) -> Subscription:
        """Raises ``StrategyNotFound``, ``StrategyArchived``, ``NoPoolForMarket`` or
        ``AlreadySubscribed``, each before anything is written. The last one is
        also what the repository raises when a concurrent request wins the race
        the ``has_live`` read cannot close."""
        strategy = await self._strategies.find(strategy_id)
        # Another author's private strategy is answered exactly as one that does not
        # exist (decision 21): the same error, so the answer does not tell them apart.
        if strategy is None or (
            strategy.visibility is Visibility.PRIVATE and strategy.author_id != user_id
        ):
            raise StrategyNotFound(f"no strategy registered under id {strategy_id}")
        if strategy.archived:
            raise StrategyArchived(f"strategy {strategy_id} is archived")

        pool_id = await self._pools.pool_id(user_id, strategy.market)
        if pool_id is None:
            raise NoPoolForMarket(
                f"you hold no pool on {'/'.join(strategy.market)}, which this strategy trades"
            )

        if await self._subscriptions.has_live(user_id, strategy_id):
            raise AlreadySubscribed(f"you are already subscribed to strategy {strategy_id}")

        subscription = Subscription(
            id=uuid4(),
            user_id=user_id,
            strategy_id=strategy_id,
            pool_id=pool_id,
            allocation_percent=allocation_percent,
            created_at=self._clock.now(),
        )
        await self._subscriptions.insert(subscription)
        await self._commit.commit()
        return subscription

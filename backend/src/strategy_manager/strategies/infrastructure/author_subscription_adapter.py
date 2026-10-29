"""Implements ``strategies.application.ports.AuthorSubscriptionPort``.

It composes the subscriptions module's own repository and pool lookup, so the
author's subscription is written exactly as ``POST /api/subscriptions`` writes
one: in the author's OWN pool for the strategy's market. It flushes and never
commits; ``RegisterStrategy`` commits the strategy and the subscription together.
"""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.strategies.application.register_strategy import PoolNotAvailable
from strategy_manager.strategies.domain.strategy import AllocationPercent, Strategy
from strategy_manager.subscriptions.domain.subscription import Subscription
from strategy_manager.subscriptions.infrastructure.adapters import SqlAlchemyUserPools
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)


class SqlAlchemyAuthorSubscription:
    def __init__(self, session: AsyncSession) -> None:
        self._pools = SqlAlchemyUserPools(session)
        self._subscriptions = SqlAlchemySubscriptionRepository(session)

    async def subscribe_author(self, strategy: Strategy, share: AllocationPercent) -> None:
        policy = strategy.policy
        market = (policy.exchange.value, policy.venue.value, policy.settlement_currency.value)
        pool_id = await self._pools.pool_id(strategy.author_id, market)
        if pool_id is None:
            # ``RegisterStrategy`` checked the author's enabled pools a moment ago,
            # so this is a pool deleted in between. Raising before the commit
            # leaves the flushed strategy row to the rollback.
            raise PoolNotAvailable(
                f"the author holds no pool on {'/'.join(market)}, which this strategy trades"
            )
        await self._subscriptions.insert(
            Subscription(
                id=uuid4(),
                user_id=strategy.author_id,
                strategy_id=strategy.id,
                pool_id=pool_id,
                allocation_percent=share,
            )
        )

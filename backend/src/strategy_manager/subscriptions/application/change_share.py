"""``ChangeShare``: a user resizes their own share of a strategy."""

from uuid import UUID

from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.errors import (
    SubscriptionNotActive,
    SubscriptionNotFound,
)
from strategy_manager.subscriptions.application.ports import (
    CommitPort,
    SubscriptionRepositoryPort,
)
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus


class ChangeShare:
    def __init__(self, subscriptions: SubscriptionRepositoryPort, commit: CommitPort) -> None:
        self._subscriptions = subscriptions
        self._commit = commit

    async def change(
        self, user_id: UUID, subscription_id: UUID, allocation_percent: AllocationPercent
    ) -> Subscription:
        """Under the row lock, so a concurrent ``Leave`` is seen: a share is never
        written onto a subscription that has just stopped being ACTIVE."""
        subscription = await self._subscriptions.get_for_update(user_id, subscription_id)
        if subscription is None:
            raise SubscriptionNotFound(f"no subscription {subscription_id}")
        if subscription.status is not SubscriptionStatus.ACTIVE:
            raise SubscriptionNotActive(
                f"subscription {subscription_id} is {subscription.status}, not ACTIVE"
            )

        changed = subscription.change_share(allocation_percent)
        await self._subscriptions.update(changed)
        await self._commit.commit()
        return changed

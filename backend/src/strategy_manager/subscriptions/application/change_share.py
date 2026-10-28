"""``ChangeShare``: a user resizes their own share of a strategy."""

import logging
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

logger = logging.getLogger(__name__)


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

        # A change of how much capital a subscription asks for leaves a trace,
        # and only a REAL change does: "changed" is decided on the decimal value
        # (33.50 over 33.5 is not one). It is written after the commit so that a
        # rolled-back change never leaves a line saying it happened. Ids and
        # values only.
        before = subscription.allocation_percent.value
        after = changed.allocation_percent.value
        if after != before:
            logger.info(
                "subscription %s to strategy %s: share of the pool changed from %s to %s",
                subscription.id,
                subscription.strategy_id,
                format(before, "f"),
                format(after, "f"),
            )
        return changed

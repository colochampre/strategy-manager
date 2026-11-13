"""``ChangeShare``: a user resizes their own share of a strategy, changes the
leverage they trade it at, or both in one write (decision 38)."""

import logging
from uuid import UUID

from strategy_manager.shared.domain.leverage import (
    Leverage,
    LeverageAboveStopCap,
    refuse_above_stop_cap,
)
from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.errors import (
    StrategyNotFound,
    SubscriptionNotActive,
    SubscriptionNotFound,
)
from strategy_manager.subscriptions.application.ports import (
    CommitPort,
    StrategyLookupPort,
    SubscriptionRepositoryPort,
)
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus

logger = logging.getLogger(__name__)


class ChangeShare:
    def __init__(
        self,
        subscriptions: SubscriptionRepositoryPort,
        commit: CommitPort,
        *,
        strategies: StrategyLookupPort,
    ) -> None:
        self._subscriptions = subscriptions
        self._commit = commit
        self._strategies = strategies

    async def change(
        self,
        user_id: UUID,
        subscription_id: UUID,
        allocation_percent: AllocationPercent | None = None,
        *,
        leverage: Leverage | None = None,
    ) -> Subscription:
        """Under the row lock, so a concurrent ``Leave`` is seen: a share or a
        leverage is never written onto a subscription that has just stopped being
        ACTIVE. What is not given is left as it is; the route refuses a request
        that gives neither."""
        subscription = await self._subscriptions.get_for_update(user_id, subscription_id)
        if subscription is None:
            raise SubscriptionNotFound(f"no subscription {subscription_id}")
        if subscription.status is not SubscriptionStatus.ACTIVE:
            raise SubscriptionNotActive(
                f"subscription {subscription_id} is {subscription.status}, not ACTIVE"
            )

        if leverage is not None:
            await self._refuse_above_stop_cap(subscription, leverage)

        changed = subscription
        if allocation_percent is not None:
            changed = changed.change_share(allocation_percent)
        if leverage is not None:
            changed = changed.change_leverage(leverage)
        await self._subscriptions.update(changed)
        await self._commit.commit()

        # A change of how much capital a subscription asks for, or of the leverage
        # it is placed at, leaves a trace, and only a REAL change does: "changed"
        # is decided on the value (33.50 over 33.5 is not one). It is written after
        # the commit so that a rolled-back change never leaves a line saying it
        # happened. Ids and values only.
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
        if changed.leverage != subscription.leverage:
            logger.info(
                "subscription %s to strategy %s: leverage changed from x%d to x%d",
                subscription.id,
                subscription.strategy_id,
                subscription.leverage.value,
                changed.leverage.value,
            )
        return changed

    async def _refuse_above_stop_cap(self, subscription: Subscription, leverage: Leverage) -> None:
        """A seat is never taken above the cap of its strategy's stop level, and
        one the author left above it (by widening the stop) is not changed for its
        user: it may be lowered to the cap, or to anything under it."""
        strategy = await self._strategies.find(subscription.strategy_id)
        if strategy is None:
            raise StrategyNotFound(f"no strategy registered under id {subscription.strategy_id}")
        try:
            refuse_above_stop_cap(leverage, strategy.stop_loss_pct)
        except LeverageAboveStopCap as exc:
            logger.warning(
                "leverage change refused, %s: user=%s subscription=%s strategy=%s %s",
                exc.reason_code,
                subscription.user_id,
                subscription.id,
                strategy.id,
                exc,
            )
            raise

"""``EndLeavingSubscription``: a LEAVING subscription ends when the strategy has
closed the last of the position it left holding (owner decision 4; tasks.md C.6).

``Leave`` marks a subscription LEAVING when its user still holds an open
allocation of the strategy, and the position then runs until the strategy closes
it. This is the other half: settling a close calls it, in the SAME transaction
that books the closing fill and under the user's pool lock (taken by the caller,
before any row lock), so no opening of the user's and no ``Leave`` can interleave.
It stages the change and never commits.
"""

from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.subscriptions.application.ports import (
    OpenAllocationPort,
    SubscriptionRepositoryPort,
)
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus


class EndLeavingSubscription:
    def __init__(
        self,
        subscriptions: SubscriptionRepositoryPort,
        allocations: OpenAllocationPort,
        clock: ClockPort,
    ) -> None:
        self._subscriptions = subscriptions
        self._allocations = allocations
        self._clock = clock

    async def end_if_flat(
        self,
        user_id: UUID,
        strategy_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
    ) -> bool:
        """Ends the user's LEAVING subscription to the strategy when the user holds
        no open allocation of it left, and returns whether it did. The row is read
        ``FOR UPDATE`` and the holding only after it, as ``Leave`` does; an ACTIVE
        subscription, or none, is left alone without reading the holding."""
        subscription = await self._subscriptions.get_live_for_update(user_id, strategy_id)
        if subscription is None or subscription.status is not SubscriptionStatus.LEAVING:
            return False
        market = (exchange, venue, settlement_currency)
        if await self._allocations.holds_open_allocation(user_id, strategy_id, market):
            return False
        await self._subscriptions.update(subscription.end(self._clock.now()))
        return True

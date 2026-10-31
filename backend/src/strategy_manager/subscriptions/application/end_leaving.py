"""``EndLeavingSubscription``: a LEAVING subscription ends when the strategy has
closed the last of the position it left holding (owner decision 4; tasks.md C.6).

``Leave`` marks a subscription LEAVING when its user still holds an open
allocation of the strategy, and the position then runs until the strategy closes
it. This is the other half: settling a close calls it, in the SAME transaction
that books the closing fill and under the user's pool lock (taken by the caller,
before any row lock), so no opening of the user's and no ``Leave`` can interleave.
It stages the change and never commits.
"""

import logging
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.subscriptions.application.ports import (
    CommitPort,
    LeavingSubscriptionsPort,
    OpenAllocationPort,
    PoolLockPort,
    SubscriptionRepositoryPort,
)
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus

logger = logging.getLogger(__name__)


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


class EndLeavingPort(Protocol):
    async def end_if_flat(
        self,
        user_id: UUID,
        strategy_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
    ) -> bool: ...


class EndFlatLeaving:
    """The worker's sweep over every user's LEAVING subscriptions (tasks.md N2, E2.3).

    A close ends a LEAVING subscription when it books the last fill. A reservation
    that ends unfilled, released by a settle or expired by the sweeper, books nothing,
    so no close ever comes for it, and the subscription would stay LEAVING for good
    with its user unable to subscribe again.

    Each decision is ``end_if_flat``, under the user's pool lock like every other. The
    commit after each one gives that lock back, so the sweep holds one at a time and
    never stalls one user's opening behind another user's decision. The listing is a
    plain read: a stale row costs one lock and a re-read that changes nothing."""

    def __init__(
        self,
        leaving: LeavingSubscriptionsPort,
        pool_lock: PoolLockPort,
        end: EndLeavingPort,
        commit: CommitPort,
    ) -> None:
        self._leaving = leaving
        self._pool_lock = pool_lock
        self._end = end
        self._commit = commit

    async def sweep(self) -> int:
        """Returns how many subscriptions it ended."""
        ended = 0
        for subscription in await self._leaving.leaving():
            exchange, venue, currency = subscription.market
            await self._pool_lock.acquire(subscription.user_id, exchange, venue, currency)
            if await self._end.end_if_flat(
                subscription.user_id, subscription.strategy_id, exchange, venue, currency
            ):
                ended += 1
                logger.info(
                    "subscription of user %s to strategy %s ended: it left, and nothing "
                    "of it is held any more",
                    subscription.user_id,
                    subscription.strategy_id,
                )
            await self._commit.commit()
        return ended

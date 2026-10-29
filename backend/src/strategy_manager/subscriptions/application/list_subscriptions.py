"""``ListSubscriptions``: a user's own subscriptions."""

from uuid import UUID

from strategy_manager.subscriptions.application.ports import SubscriptionRepositoryPort
from strategy_manager.subscriptions.domain.subscription import Subscription


class ListSubscriptions:
    def __init__(self, subscriptions: SubscriptionRepositoryPort) -> None:
        self._subscriptions = subscriptions

    async def list(self, user_id: UUID) -> list[Subscription]:
        return await self._subscriptions.list_for_user(user_id)

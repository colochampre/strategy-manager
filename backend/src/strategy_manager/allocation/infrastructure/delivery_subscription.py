"""``SqlAlchemyDeliverySubscription``: implements ``DeliverySubscriptionPort``
against the delivery's subscription row.

A plain read, taken inside the pool advisory lock: every writer that stops a
subscription taking openings holds that same lock, so no row lock is needed.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow


class SqlAlchemyDeliverySubscription:
    """Read-only: this class has no method that writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_active(self, delivery_id: UUID) -> bool:
        status = await self._session.scalar(
            select(SubscriptionRow.status)
            .join(SignalDeliveryRow, SignalDeliveryRow.subscription_id == SubscriptionRow.id)
            .where(SignalDeliveryRow.id == delivery_id)
        )
        if status is None:
            raise InvariantViolation(
                f"delivery {delivery_id} has no subscription; an opening cannot run for it"
            )
        return status == SubscriptionStatus.ACTIVE.value

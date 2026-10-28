"""Adapters of the ports ``ProcessDelivery`` and its context declare (tasks.md C.6).

Each reads another module's table through its own row, the way
``fan_out_adapters`` does: the consumer declares the port, the infrastructure
composes the providers.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.market_symbol import market_spellings
from strategy_manager.signals.application.process_signal import Delivery, UnknownDeliveryError
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.strategies.infrastructure.models import StrategyRow
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow

_DeliveryColumns = tuple[UUID, UUID, UUID, UUID, Decimal]


def _delivery_query() -> Select[_DeliveryColumns]:
    """A delivery with its SUBSCRIPTION's share, never the strategy's copy."""
    return select(
        SignalDeliveryRow.id,
        SignalDeliveryRow.signal_id,
        SignalDeliveryRow.subscription_id,
        SignalDeliveryRow.user_id,
        SubscriptionRow.allocation_percent,
    ).join(SubscriptionRow, SubscriptionRow.id == SignalDeliveryRow.subscription_id)


def _delivery(row: Row[_DeliveryColumns]) -> Delivery:
    delivery_id, signal_id, subscription_id, user_id, allocation_percent = row
    return Delivery(
        delivery_id=delivery_id,
        signal_id=signal_id,
        subscription_id=subscription_id,
        user_id=user_id,
        allocation_percent=allocation_percent,
    )


class SqlAlchemyDeliveries:
    """Implements ``DeliveryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, delivery_id: UUID) -> Delivery:
        found = (
            await self._session.execute(
                _delivery_query().where(SignalDeliveryRow.id == delivery_id)
            )
        ).first()
        if found is None:
            raise UnknownDeliveryError(f"no delivery registered for id {delivery_id}")
        return _delivery(found)

    async def of_signal_author(self, signal_id: UUID) -> Delivery:
        found = (
            await self._session.execute(
                _delivery_query()
                .join(SignalRow, SignalRow.id == SignalDeliveryRow.signal_id)
                .join(StrategyRow, StrategyRow.id == SignalRow.strategy_id)
                .where(
                    SignalDeliveryRow.signal_id == signal_id,
                    SignalDeliveryRow.user_id == StrategyRow.author_id,
                )
            )
        ).first()
        if found is None:
            raise UnknownDeliveryError(
                f"signal {signal_id} has no delivery for its strategy's author; the "
                "reverse continuation cannot open without one"
            )
        return _delivery(found)

    async def author_delivery_id(self, signal_id: UUID) -> UUID:
        """``OpenAfterClose``'s narrow view of ``of_signal_author``: only the id,
        for the outcome an abandonment records on that delivery."""
        return (await self.of_signal_author(signal_id)).delivery_id


class SqlAlchemySubscriptionReservations:
    """Implements ``SubscriptionReservationsPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_before(
        self,
        subscription_id: UUID,
        user_id: UUID,
        strategy_id: UUID,
        symbol: str,
        received_at: datetime,
    ) -> UUID | None:
        """A reservation carries no symbol, so it is matched through the signal it
        was made for, under every spelling of the market. It belongs to the
        subscription through its delivery, and the user filter is the repository
        convention: another user's reservation is never returned."""
        found = (
            await self._session.execute(
                select(ReservationRow.id)
                .join(SignalDeliveryRow, SignalDeliveryRow.id == ReservationRow.delivery_id)
                .join(SignalRow, SignalRow.id == ReservationRow.signal_id)
                .where(
                    SignalDeliveryRow.subscription_id == subscription_id,
                    ReservationRow.user_id == user_id,
                    ReservationRow.strategy_id == strategy_id,
                    func.upper(SignalRow.symbol).in_(market_spellings(symbol)),
                    SignalRow.received_at < received_at,
                )
                .order_by(SignalRow.received_at.desc(), ReservationRow.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return found

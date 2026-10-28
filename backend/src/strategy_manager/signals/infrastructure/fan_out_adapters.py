"""Adapters of the ports ``FanOutSignal`` declares (tasks.md C.5).

Each reads another module's table through its own row or repository, the way
``subscriptions.infrastructure.adapters`` does: the consumer declares the port,
the infrastructure composes the providers.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.domain.reservation import ReservationStatus
from strategy_manager.allocation.infrastructure.models import ReservationRow
from strategy_manager.execution.domain.market_symbol import market_spellings
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.signals.application.fan_out_signal import SignalFacts, Subscriber
from strategy_manager.signals.application.ports import PoolKey, SignalRepositoryPort
from strategy_manager.signals.infrastructure.models import SignalDeliveryRow, SignalRow
from strategy_manager.signals.infrastructure.signal_context import UnknownSignalError
from strategy_manager.subscriptions.domain.subscription import SubscriptionStatus
from strategy_manager.subscriptions.infrastructure.models import SubscriptionRow

_LIVE_RESERVATION = (ReservationStatus.PENDING.value, ReservationStatus.SUBMITTED.value)
_LIVE = (SubscriptionStatus.ACTIVE.value, SubscriptionStatus.LEAVING.value)


class SignalFactsAdapter:
    """Implements ``SignalFactsPort`` over the same lookups
    ``SignalContextAdapter`` makes for ``ProcessSignalHandler``: the signal, and
    the most recent earlier signal of the same strategy and market."""

    def __init__(self, signals: SignalRepositoryPort) -> None:
        self._signals = signals

    async def load(self, signal_id: UUID) -> SignalFacts:
        signal = await self._signals.get_by_id(signal_id)
        if signal is None:
            raise UnknownSignalError(f"no signal registered for id {signal_id}")
        assert signal.received_at is not None
        prior = await self._signals.find_prior(
            signal.strategy_id, signal.symbol, signal.received_at
        )
        return SignalFacts(
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            position_size=signal.position_size,
            prior_position_size=prior.position_size if prior is not None else None,
            received_at=signal.received_at,
        )


class SqlAlchemySubscribers:
    """Implements ``SubscribersPort``."""

    def __init__(self, session: AsyncSession, holdings: ReadSymbolHoldings) -> None:
        self._session = session
        self._holdings = holdings

    async def active(self, strategy_id: UUID, received_at: datetime) -> list[Subscriber]:
        return await self._subscribers(
            strategy_id, (SubscriptionStatus.ACTIVE.value,), received_at
        )

    async def live_holders(
        self, strategy_id: UUID, symbol: str, pool: PoolKey, received_at: datetime
    ) -> list[Subscriber]:
        live = await self._subscribers(strategy_id, _LIVE, received_at)
        return [
            subscriber
            for subscriber in live
            if await self._holds(subscriber.user_id, strategy_id, symbol, pool)
        ]

    async def _subscribers(
        self, strategy_id: UUID, statuses: tuple[str, ...], received_at: datetime
    ) -> list[Subscriber]:
        result = await self._session.execute(
            select(SubscriptionRow.id, SubscriptionRow.user_id, SubscriptionRow.status)
            .where(
                SubscriptionRow.strategy_id == strategy_id,
                SubscriptionRow.status.in_(statuses),
                SubscriptionRow.created_at <= received_at,
            )
            .order_by(SubscriptionRow.created_at, SubscriptionRow.id)
        )
        return [
            Subscriber(
                subscription_id=subscription_id,
                user_id=user_id,
                active=status == SubscriptionStatus.ACTIVE.value,
            )
            for subscription_id, user_id, status in result.all()
        ]

    async def _holds(self, user_id: UUID, strategy_id: UUID, symbol: str, pool: PoolKey) -> bool:
        """This user's open allocation of the strategy on THIS symbol, the question
        ``OpenAllocationAdapter`` asks for every symbol: the ledger's allocations
        (per allocation, never netted across them, under every spelling of the
        symbol), and a reservation of the user still holding capital. A reservation
        carries no symbol, so it is matched through the signal that opened it."""
        held = await self._holdings.symbol_holdings(user_id, pool, symbol)
        if any(allocation.strategy_id == strategy_id for allocation in held):
            return True

        exchange, venue, currency = pool
        reserved = (
            await self._session.execute(
                select(ReservationRow.id)
                .join(SignalRow, SignalRow.id == ReservationRow.signal_id)
                .where(
                    ReservationRow.user_id == user_id,
                    ReservationRow.strategy_id == strategy_id,
                    ReservationRow.exchange == exchange,
                    ReservationRow.venue == venue,
                    ReservationRow.settlement_currency == currency,
                    ReservationRow.status.in_(_LIVE_RESERVATION),
                    ReservationRow.terminal_at.is_(None),
                    func.upper(SignalRow.symbol).in_(market_spellings(symbol)),
                )
                .limit(1)
            )
        ).first()
        return reserved is not None


class SqlAlchemyDeliveryRepository:
    """Implements ``DeliveryRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure(
        self, signal_id: UUID, subscriptions: Sequence[Subscriber]
    ) -> dict[UUID, UUID]:
        if not subscriptions:
            return {}
        await self._session.execute(
            pg_insert(SignalDeliveryRow)
            .values(
                [
                    {
                        "id": uuid4(),
                        "signal_id": signal_id,
                        "subscription_id": subscriber.subscription_id,
                        "user_id": subscriber.user_id,
                        "status": "ACCEPTED",
                    }
                    for subscriber in subscriptions
                ]
            )
            .on_conflict_do_nothing(index_elements=["signal_id", "subscription_id"])
        )
        # ``DO NOTHING`` returns no row for a conflict, so the ids are read back:
        # a delivery that already existed still needs its job.
        found = await self._session.execute(
            select(SignalDeliveryRow.subscription_id, SignalDeliveryRow.id).where(
                SignalDeliveryRow.signal_id == signal_id,
                SignalDeliveryRow.subscription_id.in_(
                    [subscriber.subscription_id for subscriber in subscriptions]
                ),
            )
        )
        return {subscription_id: delivery_id for subscription_id, delivery_id in found.all()}

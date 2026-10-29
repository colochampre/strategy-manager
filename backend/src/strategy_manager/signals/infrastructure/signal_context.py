"""Implements ``signals.application.process_signal.SignalContextPort`` by
composing the ``signals``, ``strategies`` and ``allocation`` read ports —
everything ``ProcessDelivery`` needs to route a signal by
``PositionTransition`` (design.md § "position_size routes the signal"), as ONE
subscription sees it (multi-user design AD5; tasks.md C.6).
"""

from decimal import Decimal

from strategy_manager.allocation.application.ports import ReservationRepositoryPort
from strategy_manager.signals.application.ports import (
    SignalRepositoryPort,
    SubscriptionReservationsPort,
)
from strategy_manager.signals.application.process_signal import Delivery, SignalContext
from strategy_manager.signals.domain.signal import WebhookSignal
from strategy_manager.strategies.application.policy_adapter import UnknownStrategyError
from strategy_manager.strategies.application.ports import StrategyRepositoryPort


class UnknownSignalError(Exception):
    """Raised when ``ProcessDelivery`` is asked to load a signal id
    that has no matching row — a misconfiguration, not a business outcome."""


class SignalContextAdapter:
    """Implements ``signals.application.process_signal.SignalContextPort``."""

    def __init__(
        self,
        signals: SignalRepositoryPort,
        strategies: StrategyRepositoryPort,
        reservations: ReservationRepositoryPort,
        subscription_reservations: SubscriptionReservationsPort,
    ) -> None:
        self._signals = signals
        self._strategies = strategies
        self._reservations = reservations
        self._subscription_reservations = subscription_reservations

    async def load(self, delivery: Delivery) -> SignalContext:
        signal = await self._signals.get_by_id(delivery.signal_id)
        if signal is None:
            raise UnknownSignalError(f"no signal registered for id {delivery.signal_id}")

        strategy = await self._strategies.get_by_id(signal.strategy_id)
        if strategy is None:
            raise UnknownStrategyError(f"no strategy registered for id {signal.strategy_id}")

        assert signal.received_at is not None
        # The position is the strategy's (one per strategy and symbol); the
        # reservation a close works is the SUBSCRIPTION's own. Reading the
        # author's here would have a second delivery resume or trade the
        # author's reservation: a silent wrong-user bug.
        prior_position_size = await self._prior_position_size(signal)
        prior_reservation_id = await self._subscription_reservations.latest_before(
            delivery.subscription_id,
            delivery.user_id,
            signal.strategy_id,
            signal.symbol,
            signal.received_at,
        )
        own_reservation = await self._reservations.find_by_signal_id(
            delivery.user_id, delivery.signal_id
        )

        return SignalContext(
            strategy_id=signal.strategy_id,
            symbol=signal.symbol,
            price=signal.price,
            position_size=signal.position_size,
            prior_position_size=prior_position_size,
            prior_reservation_id=prior_reservation_id,
            settlement_currency=strategy.policy.settlement_currency.value,
            own_reservation_id=own_reservation.id if own_reservation is not None else None,
            received_at=signal.received_at,
        )

    async def _prior_position_size(self, signal: WebhookSignal) -> Decimal | None:
        assert signal.received_at is not None
        prior_signal = await self._signals.find_prior(
            signal.strategy_id, signal.symbol, signal.received_at
        )
        return prior_signal.position_size if prior_signal is not None else None

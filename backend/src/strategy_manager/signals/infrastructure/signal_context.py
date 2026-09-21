"""Implements ``signals.application.process_signal.SignalContextPort`` by
composing the ``signals``, ``strategies`` and ``allocation`` read ports —
everything ``ProcessSignalHandler`` needs to route a signal by
``PositionTransition`` (design.md § "position_size routes the signal").
"""

from decimal import Decimal
from uuid import UUID

from strategy_manager.allocation.application.ports import ReservationRepositoryPort
from strategy_manager.signals.application.ports import SignalRepositoryPort
from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.domain.signal import WebhookSignal
from strategy_manager.strategies.application.policy_adapter import UnknownStrategyError
from strategy_manager.strategies.application.ports import StrategyRepositoryPort


class UnknownSignalError(Exception):
    """Raised when ``ProcessSignalHandler`` is asked to load a signal id
    that has no matching row — a misconfiguration, not a business outcome."""


class SignalContextAdapter:
    """Implements ``signals.application.process_signal.SignalContextPort``."""

    def __init__(
        self,
        signals: SignalRepositoryPort,
        strategies: StrategyRepositoryPort,
        reservations: ReservationRepositoryPort,
    ) -> None:
        self._signals = signals
        self._strategies = strategies
        self._reservations = reservations

    async def load(self, signal_id: UUID) -> SignalContext:
        signal = await self._signals.get_by_id(signal_id)
        if signal is None:
            raise UnknownSignalError(f"no signal registered for id {signal_id}")

        strategy = await self._strategies.get_by_id(signal.strategy_id)
        if strategy is None:
            raise UnknownStrategyError(f"no strategy registered for id {signal.strategy_id}")

        prior_position_size, prior_reservation_id = await self._prior_state(signal)

        assert signal.received_at is not None
        own_reservation = await self._reservations.find_by_signal_id(signal_id)

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

    async def _prior_state(
        self, signal: WebhookSignal
    ) -> tuple[Decimal | None, UUID | None]:
        assert signal.received_at is not None
        prior_signal = await self._signals.find_prior(
            signal.strategy_id, signal.symbol, signal.received_at
        )
        if prior_signal is None:
            return None, None

        assert prior_signal.id is not None
        prior_reservation = await self._reservations.find_by_signal_id(prior_signal.id)
        prior_reservation_id = prior_reservation.id if prior_reservation is not None else None
        return prior_signal.position_size, prior_reservation_id

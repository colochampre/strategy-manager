"""Adapts ``execution``'s ``SettleOutcomeRecorderPort`` onto
``DeliveryOutcomePort`` (decision 25, design.md "Addendum: signal outcomes"
§ B rows 16-17; tasks.md C.7).

Lives in ``signals`` because only ``signals`` knows what a delivery outcome is,
and what KIND of signal an attempt settles: ``execution`` declares the narrow
port it needs and never imports this side.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.application.ports import DeliveryOutcomePort, SignalRepositoryPort
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.position_transition import PositionTransition, TransitionKind
from strategy_manager.signals.domain.signal import WebhookSignal

ORDER_NEVER_REACHED_EXCHANGE = "ORDER_NEVER_REACHED_EXCHANGE"


class SignalSettleOutcomeRecorder:
    """Stages the write on the outcome adapter's session; never commits."""

    def __init__(self, outcomes: DeliveryOutcomePort, signals: SignalRepositoryPort) -> None:
        self._outcomes = outcomes
        self._signals = signals

    async def record_open_filled(self, delivery_id: UUID) -> None:
        await self._outcomes.record(delivery_id, SignalOutcome.processed())

    async def record_close_filled(self, delivery_id: UUID, signal_id: UUID) -> None:
        # Decision 26: a REVERSE's close half never ends the delivery, whether
        # the open half is still pending (PROCESSING) or a spot REVERSE
        # already ended REJECTED ``REVERSE_NEW_SIDE_UNHOLDABLE`` (row 18).
        # Writing here would either block the open half through the terminal
        # guard or hit that guard with a differing PROCESSED and a WARNING on
        # every such trade.
        if await is_reverse(self._signals, signal_id):
            return
        await self._outcomes.record(delivery_id, SignalOutcome.processed())

    async def record_never_placed(self, delivery_id: UUID, detail: str) -> None:
        # Unlike a filled close, a REVERSE whose close never reached the
        # exchange ends here: nothing executed, so no open half will follow,
        # and a refused close ends the delivery with the CLOSE's code.
        await self._outcomes.record(
            delivery_id, SignalOutcome.rejected(ORDER_NEVER_REACHED_EXCHANGE, detail)
        )


class SignalKindReadPort(Protocol):
    """The two reads that tell a signal's transition kind."""

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None: ...

    async def find_prior(
        self, strategy_id: UUID, symbol: str, before: datetime
    ) -> WebhookSignal | None: ...


async def is_reverse(signals: SignalKindReadPort, signal_id: UUID) -> bool:
    """Derives the transition kind exactly as ``SignalContextAdapter``
    does when ``delivery.process`` routes the delivery: this signal's
    ``position_size`` against the previous signal's for the same strategy
    and symbol. The kind is not stored anywhere, but both inputs are
    immutable, so the answer cannot differ from the one routing used."""
    signal = await signals.get_by_id(signal_id)
    if signal is None or signal.received_at is None:
        raise InvariantViolation(f"cannot settle an outcome for unknown signal {signal_id}")
    prior = await signals.find_prior(signal.strategy_id, signal.symbol, signal.received_at)
    transition = PositionTransition.classify(
        prior.position_size if prior is not None else None, signal.position_size
    )
    return transition.kind is TransitionKind.REVERSE

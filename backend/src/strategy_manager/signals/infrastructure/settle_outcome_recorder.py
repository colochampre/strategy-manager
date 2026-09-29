"""Adapts ``execution``'s ``SettleOutcomeRecorderPort`` onto
``SignalOutcomePort`` (decision 25, design.md "Addendum: signal outcomes"
§ B rows 16-17).

Lives in ``signals`` because only ``signals`` knows what a signal outcome is,
and what KIND of signal an attempt settles: ``execution`` declares the narrow
port it needs and never imports this side.
"""

from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.application.ports import SignalOutcomePort, SignalRepositoryPort
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.position_transition import PositionTransition, TransitionKind

ORDER_NEVER_REACHED_EXCHANGE = "ORDER_NEVER_REACHED_EXCHANGE"


class SignalSettleOutcomeRecorder:
    """Stages the write on the outcome adapter's session; never commits."""

    def __init__(self, outcomes: SignalOutcomePort, signals: SignalRepositoryPort) -> None:
        self._outcomes = outcomes
        self._signals = signals

    async def record_open_filled(self, signal_id: UUID) -> None:
        await self._outcomes.record(signal_id, SignalOutcome.processed())

    async def record_close_filled(self, signal_id: UUID) -> None:
        # Decision 26: a REVERSE's close half never ends the signal, whether
        # the open half is still pending (PROCESSING) or a spot REVERSE
        # already ended REJECTED ``REVERSE_NEW_SIDE_UNHOLDABLE`` (row 18).
        # Writing here would either block the open half through the terminal
        # guard or hit that guard with a differing PROCESSED and a WARNING on
        # every such trade.
        if await self._is_reverse(signal_id):
            return
        await self._outcomes.record(signal_id, SignalOutcome.processed())

    async def record_never_placed(self, signal_id: UUID, detail: str) -> None:
        # Unlike a filled close, a REVERSE whose close never reached the
        # exchange ends here: nothing executed, so no open half will follow,
        # and a refused close ends the signal with the CLOSE's code.
        await self._outcomes.record(
            signal_id, SignalOutcome.rejected(ORDER_NEVER_REACHED_EXCHANGE, detail)
        )

    async def _is_reverse(self, signal_id: UUID) -> bool:
        """Derives the transition kind exactly as ``SignalContextAdapter``
        does when ``signal.process`` routes the signal: this signal's
        ``position_size`` against the previous signal's for the same strategy
        and symbol. The kind is not stored anywhere, but both inputs are
        immutable, so the answer cannot differ from the one routing used."""
        signal = await self._signals.get_by_id(signal_id)
        if signal is None or signal.received_at is None:
            raise InvariantViolation(
                f"cannot settle an outcome for unknown signal {signal_id}"
            )
        prior = await self._signals.find_prior(
            signal.strategy_id, signal.symbol, signal.received_at
        )
        transition = PositionTransition.classify(
            prior.position_size if prior is not None else None, signal.position_size
        )
        return transition.kind is TransitionKind.REVERSE

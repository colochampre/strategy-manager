"""Adapts ``execution``'s ``OrderOutcomeRecorderPort`` onto
``DeliveryOutcomePort`` (decision 25, design.md "Addendum: signal outcomes"
§ C, rows 9-15; tasks.md C.7).

Lives in ``signals`` because only ``signals`` knows what a delivery outcome is;
``execution`` declares the narrow port it needs and never imports this side.
"""

from uuid import UUID

from strategy_manager.signals.application.ports import DeliveryOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.infrastructure.settle_outcome_recorder import (
    SignalKindReadPort,
    is_reverse,
)


class SignalOrderOutcomeRecorder:
    """Stages the write on the outcome adapter's session; never commits."""

    def __init__(self, outcomes: DeliveryOutcomePort, signals: SignalKindReadPort) -> None:
        self._outcomes = outcomes
        self._signals = signals

    async def record_close_already_flat(
        self, delivery_id: UUID, signal_id: UUID, detail: str
    ) -> None:
        # Owner decision 2026-11-13 (SS.7, A): a reverse's open half still follows, once
        # the stop watcher books the stop. Writing PROCESSED here would block it through
        # the terminal guard, exactly as decision 26 keeps a filled reverse close silent.
        if await is_reverse(self._signals, signal_id):
            return
        await self._outcomes.record(delivery_id, SignalOutcome.processed("ALREADY_FLAT", detail))

    async def record_processing(self, delivery_id: UUID) -> None:
        await self._outcomes.record(delivery_id, SignalOutcome.processing())

    async def record_rejected(self, delivery_id: UUID, reason: str, detail: str) -> None:
        await self._outcomes.record(delivery_id, SignalOutcome.rejected(reason, detail))

    async def record_processed(self, delivery_id: UUID, reason: str, detail: str) -> None:
        await self._outcomes.record(delivery_id, SignalOutcome.processed(reason, detail))

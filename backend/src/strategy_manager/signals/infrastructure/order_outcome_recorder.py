"""Adapts ``execution``'s ``OrderOutcomeRecorderPort`` onto
``SignalOutcomePort`` (decision 25, design.md "Addendum: signal outcomes"
§ C, rows 9-15).

Lives in ``signals`` because only ``signals`` knows what a signal outcome is;
``execution`` declares the narrow port it needs and never imports this side.
"""

from uuid import UUID

from strategy_manager.signals.application.ports import SignalOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome


class SignalOrderOutcomeRecorder:
    """Stages the write on the outcome adapter's session; never commits."""

    def __init__(self, outcomes: SignalOutcomePort) -> None:
        self._outcomes = outcomes

    async def record_processing(self, signal_id: UUID) -> None:
        await self._outcomes.record(signal_id, SignalOutcome.processing())

    async def record_rejected(self, signal_id: UUID, reason: str, detail: str) -> None:
        await self._outcomes.record(signal_id, SignalOutcome.rejected(reason, detail))

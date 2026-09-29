"""Adapts ``allocation``'s ``SkipRecorderPort`` onto ``SignalOutcomePort``
(decision 25, design.md "Addendum: signal outcomes" § C, row 8).

Lives in ``signals`` because only ``signals`` knows what a signal outcome is;
``allocation`` declares the narrow port it needs and never imports this side.
"""

from uuid import UUID

from strategy_manager.signals.application.ports import SignalOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome


class SignalSkipRecorder:
    """A skip ends the signal ``REJECTED`` with the skip reason as its code.
    Stages the write on the outcome adapter's session; never commits."""

    def __init__(self, outcomes: SignalOutcomePort) -> None:
        self._outcomes = outcomes

    async def record_skip(self, signal_id: UUID, reason: str, detail: str) -> None:
        await self._outcomes.record(signal_id, SignalOutcome.rejected(reason, detail))

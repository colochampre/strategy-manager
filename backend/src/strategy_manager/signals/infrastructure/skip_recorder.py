"""Adapts ``allocation``'s ``SkipRecorderPort`` onto ``DeliveryOutcomePort``
(decision 25, design.md "Addendum: signal outcomes" § C, row 8; tasks.md C.7).

Lives in ``signals`` because only ``signals`` knows what a delivery outcome is;
``allocation`` declares the narrow port it needs and never imports this side.
"""

from uuid import UUID

from strategy_manager.signals.application.ports import DeliveryOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome


class SignalSkipRecorder:
    """A skip ends the DELIVERY ``REJECTED`` with the skip reason as its code.
    Stages the write on the outcome adapter's session; never commits.

    ``AllocateCapital`` hands this the delivery id. The port it implements
    (``allocation.application.ports.SkipRecorderPort``) still names that first
    parameter ``signal_id``: renaming it is outside C.7's edit surface."""

    def __init__(self, outcomes: DeliveryOutcomePort) -> None:
        self._outcomes = outcomes

    async def record_skip(self, delivery_id: UUID, reason: str, detail: str) -> None:
        await self._outcomes.record(delivery_id, SignalOutcome.rejected(reason, detail))

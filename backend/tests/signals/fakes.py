"""Shared fake for ``SignalOutcomePort`` (decision 25)."""

from dataclasses import dataclass, field
from uuid import UUID

from strategy_manager.signals.domain.outcome import SignalOutcome


@dataclass
class RecordingSignalOutcomes:
    calls: list[tuple[UUID, SignalOutcome]] = field(default_factory=list)

    async def record(self, signal_id: UUID, outcome: SignalOutcome) -> None:
        self.calls.append((signal_id, outcome))

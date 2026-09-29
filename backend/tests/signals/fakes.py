"""Shared fake for ``SignalOutcomePort`` (decision 25)."""

from dataclasses import dataclass, field
from uuid import UUID

from strategy_manager.signals.domain.outcome import SignalOutcome


@dataclass
class RecordingSignalOutcomes:
    """``calls`` are ``record`` calls (settle, signal.process: a conflict with
    a terminal signal warns); ``unless_terminal_calls`` are the silent path's
    (continuation abandonments, exhausted jobs). ``log`` (optional) receives
    ``"outcome.record"`` / ``"outcome.unless_terminal"`` in call order."""

    calls: list[tuple[UUID, SignalOutcome]] = field(default_factory=list)
    unless_terminal_calls: list[tuple[UUID, SignalOutcome]] = field(default_factory=list)
    log: list[str] | None = None

    async def record(self, signal_id: UUID, outcome: SignalOutcome) -> None:
        self.calls.append((signal_id, outcome))
        if self.log is not None:
            self.log.append("outcome.record")

    async def record_unless_terminal(self, signal_id: UUID, outcome: SignalOutcome) -> None:
        self.unless_terminal_calls.append((signal_id, outcome))
        if self.log is not None:
            self.log.append("outcome.unless_terminal")

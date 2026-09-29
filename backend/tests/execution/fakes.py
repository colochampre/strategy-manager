"""Shared fake for ``OrderOutcomeRecorderPort`` (decision 25, rows 9-15)."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class RecordingOrderOutcomes:
    """Records every outcome a use case asked to stage. ``log`` (optional)
    receives ``"outcome.processing"`` / ``"outcome.rejected"`` in call order,
    so a test can prove the write was staged BEFORE the commit."""

    processing: list[UUID] = field(default_factory=list)
    rejected: list[tuple[UUID, str, str]] = field(default_factory=list)
    log: list[str] | None = None

    async def record_processing(self, signal_id: UUID) -> None:
        self.processing.append(signal_id)
        if self.log is not None:
            self.log.append("outcome.processing")

    async def record_rejected(self, signal_id: UUID, reason: str, detail: str) -> None:
        self.rejected.append((signal_id, reason, detail))
        if self.log is not None:
            self.log.append("outcome.rejected")


@dataclass
class RecordingSettleOutcomes:
    """Shared fake for ``SettleOutcomeRecorderPort`` (decision 25, rows
    16-17). ``log`` (optional) receives ``"outcome.<method>"`` in call order,
    so a test can prove the write was staged BEFORE the commit."""

    open_filled: list[UUID] = field(default_factory=list)
    close_filled: list[UUID] = field(default_factory=list)
    never_placed: list[tuple[UUID, str]] = field(default_factory=list)
    log: list[str] | None = None

    async def record_open_filled(self, signal_id: UUID) -> None:
        self.open_filled.append(signal_id)
        if self.log is not None:
            self.log.append("outcome.open_filled")

    async def record_close_filled(self, signal_id: UUID) -> None:
        self.close_filled.append(signal_id)
        if self.log is not None:
            self.log.append("outcome.close_filled")

    async def record_never_placed(self, signal_id: UUID, detail: str) -> None:
        self.never_placed.append((signal_id, detail))
        if self.log is not None:
            self.log.append("outcome.never_placed")

    @property
    def nothing(self) -> bool:
        return not (self.open_filled or self.close_filled or self.never_placed)

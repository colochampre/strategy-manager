"""Shared fake for ``SkipRecorderPort`` (decision 25, row 8)."""

from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class RecordingSkipRecorder:
    """Records every skip ``AllocateCapital`` asked to persist, and how many
    commits had happened at that moment when ``commit`` is supplied, so a
    test can prove the write was staged BEFORE the commit."""

    calls: list[tuple[UUID, str, str]] = field(default_factory=list)

    async def record_skip(self, signal_id: UUID, reason: str, detail: str) -> None:
        self.calls.append((signal_id, reason, detail))

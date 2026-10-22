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


class AlwaysEnabledPool:
    """``PoolStatusPort`` for tests that are not about the pool flag: the pool
    is never reported disabled, so ``AllocateCapital`` behaves as it did before
    the in-lock pool check existed."""

    async def is_disabled(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> bool:
        return False


@dataclass
class RecordingPoolStatus:
    """``PoolStatusPort`` whose answer is scripted and whose calls are recorded,
    each with the ``events`` log it shares with the fakes around it so a test
    can prove the read came after the lock. ``users`` records whose pool each
    call asked about (multi-user design AD8)."""

    disabled: bool
    events: list[str] = field(default_factory=list)
    calls: list[tuple[str, str, str]] = field(default_factory=list)
    users: list[UUID] = field(default_factory=list)

    async def is_disabled(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> bool:
        self.users.append(user_id)
        self.calls.append((exchange, venue, settlement_currency))
        self.events.append("pool_status")
        return self.disabled

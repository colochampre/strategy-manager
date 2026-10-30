"""Shared fakes for ``OrderOutcomeRecorderPort`` (decision 25, rows 9-15) and
``SettleOutcomeRecorderPort`` (rows 16-17). Since tasks.md C.7 every id they record
is a DELIVERY's."""

from dataclasses import dataclass, field
from uuid import UUID

from strategy_manager.execution.application.ports import ExchangeRegistryPort
from strategy_manager.shared.domain.mode import Mode


@dataclass
class OneRegistry:
    """``ModeExchangesPort`` for a test that is not about which adapter a mode gets:
    every mode gets ``registry``. ``asked`` records the modes in call order."""

    registry: ExchangeRegistryPort
    asked: list[Mode] = field(default_factory=list)

    async def for_mode(self, mode: Mode) -> ExchangeRegistryPort:
        self.asked.append(mode)
        return self.registry


@dataclass
class RecordingOrderOutcomes:
    """Records every outcome a use case asked to stage. ``log`` (optional)
    receives ``"outcome.processing"`` / ``"outcome.rejected"`` in call order,
    so a test can prove the write was staged BEFORE the commit."""

    processing: list[UUID] = field(default_factory=list)
    rejected: list[tuple[UUID, str, str]] = field(default_factory=list)
    log: list[str] | None = None

    async def record_processing(self, delivery_id: UUID) -> None:
        self.processing.append(delivery_id)
        if self.log is not None:
            self.log.append("outcome.processing")

    async def record_rejected(self, delivery_id: UUID, reason: str, detail: str) -> None:
        self.rejected.append((delivery_id, reason, detail))
        if self.log is not None:
            self.log.append("outcome.rejected")


@dataclass
class RecordingSettleOutcomes:
    """Shared fake for ``SettleOutcomeRecorderPort`` (decision 25, rows
    16-17). ``log`` (optional) receives ``"outcome.<method>"`` in call order,
    so a test can prove the write was staged BEFORE the commit.
    ``close_filled`` holds the delivery ids and ``close_filled_signals`` the
    signal ids passed beside them."""

    open_filled: list[UUID] = field(default_factory=list)
    close_filled: list[UUID] = field(default_factory=list)
    close_filled_signals: list[UUID] = field(default_factory=list)
    never_placed: list[tuple[UUID, str]] = field(default_factory=list)
    log: list[str] | None = None

    async def record_open_filled(self, delivery_id: UUID) -> None:
        self.open_filled.append(delivery_id)
        if self.log is not None:
            self.log.append("outcome.open_filled")

    async def record_close_filled(self, delivery_id: UUID, signal_id: UUID) -> None:
        self.close_filled.append(delivery_id)
        self.close_filled_signals.append(signal_id)
        if self.log is not None:
            self.log.append("outcome.close_filled")

    async def record_never_placed(self, delivery_id: UUID, detail: str) -> None:
        self.never_placed.append((delivery_id, detail))
        if self.log is not None:
            self.log.append("outcome.never_placed")

    @property
    def nothing(self) -> bool:
        return not (self.open_filled or self.close_filled or self.never_placed)

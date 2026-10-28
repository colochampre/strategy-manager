"""Shared fakes for ``SignalOutcomePort`` and ``DeliveryOutcomePort`` (decision 25;
tasks.md C.7) and ``TradeCapabilityPort`` (decisions 18 and 20)."""

from dataclasses import dataclass, field
from uuid import UUID

from strategy_manager.signals.application.ports import TradeCapability
from strategy_manager.signals.domain.outcome import SignalOutcome


@dataclass
class FakeTradeCapability:
    """Answers ``answer`` for every exchange and records which exchanges it
    was asked about, so a test can prove the handler consulted it (or, for a
    close, never did), and whose key (``users``)."""

    answer: TradeCapability = TradeCapability.TRADE_CAPABLE
    asked: list[str] = field(default_factory=list)
    users: list[UUID] = field(default_factory=list)

    async def capability(self, user_id: UUID, exchange: str) -> TradeCapability:
        self.users.append(user_id)
        self.asked.append(exchange)
        return self.answer


@dataclass
class RecordingSignalOutcomes:
    """Stands in for both outcome ports; the id it records is the row's: a
    DELIVERY's for ``DeliveryOutcomePort`` and a SIGNAL's for ``SignalOutcomePort``.
    The single-subscriber tests run in a world where a delivery's id IS its signal's
    (``delivery_support.SoleSubscriberDeliveries``), so their assertions on that id
    mean the same thing for either.

    ``calls`` are ``record`` calls (settle, delivery.process: a conflict with a
    terminal outcome warns); ``unless_terminal_calls`` are the silent path's
    (continuation abandonments, exhausted jobs). ``log`` (optional) receives
    ``"outcome.record"`` / ``"outcome.unless_terminal"`` in call order."""

    calls: list[tuple[UUID, SignalOutcome]] = field(default_factory=list)
    unless_terminal_calls: list[tuple[UUID, SignalOutcome]] = field(default_factory=list)
    log: list[str] | None = None

    async def record(self, row_id: UUID, outcome: SignalOutcome) -> None:
        self.calls.append((row_id, outcome))
        if self.log is not None:
            self.log.append("outcome.record")

    async def record_unless_terminal(self, row_id: UUID, outcome: SignalOutcome) -> None:
        self.unless_terminal_calls.append((row_id, outcome))
        if self.log is not None:
            self.log.append("outcome.unless_terminal")


class SoleSubscriberDeliverySignals:
    """``DeliverySignalPort`` for the single-subscriber world: a delivery has its
    signal's own id."""

    async def signal_of(self, delivery_id: UUID) -> UUID:
        return delivery_id

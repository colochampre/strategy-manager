"""Shared fake for ``SkipRecorderPort`` (decision 25, row 8)."""

from dataclasses import dataclass, field
from uuid import UUID

from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.trade_capability import TradeCapability


@dataclass
class RecordingSkipRecorder:
    """Records every skip ``AllocateCapital`` asked to persist, and how many
    commits had happened at that moment when ``commit`` is supplied, so a
    test can prove the write was staged BEFORE the commit."""

    calls: list[tuple[UUID, str, str]] = field(default_factory=list)

    async def record_skip(self, signal_id: UUID, reason: str, detail: str) -> None:
        self.calls.append((signal_id, reason, detail))


@dataclass
class ActiveSubscription:
    """``DeliverySubscriptionPort`` for tests that are not about leaving: the
    subscription takes openings unless ``active`` says otherwise. ``asked`` records
    the delivery of each call and ``events`` is shared with the fakes around it, so
    a test can prove the read came after the lock."""

    active: bool = True
    asked: list[UUID] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    async def is_active(self, delivery_id: UUID) -> bool:
        self.asked.append(delivery_id)
        self.events.append("subscription_state")
        return self.active


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


@dataclass
class FixedUserMode:
    """``UserModePort`` for tests that are not about the mode: every opening runs
    in ``mode`` (``LIVE`` by default, what a reservation recorded before the mode
    existed became). ``users`` and ``events`` record the calls, ``events`` shared
    with the fakes around it so a test can prove the read came after the lock."""

    mode: Mode = Mode.LIVE
    events: list[str] = field(default_factory=list)
    users: list[UUID] = field(default_factory=list)

    async def effective_mode(self, user_id: UUID) -> Mode:
        self.users.append(user_id)
        self.events.append("user_mode")
        return self.mode

    async def current_mode(self, user_id: UUID) -> Mode:
        self.users.append(user_id)
        return self.mode


@dataclass
class RecordedModes:
    """``AllocationModePort``: every allocation opened in ``mode`` (``LIVE`` by
    default, for tests that are not about the mode), unless ``by_allocation`` names
    it. ``asked`` records the ``(user, allocation)`` of each call."""

    mode: Mode = Mode.LIVE
    by_allocation: dict[UUID, Mode] = field(default_factory=dict)
    asked: list[tuple[UUID, UUID]] = field(default_factory=list)

    async def mode_of(self, user_id: UUID, allocation_id: UUID) -> Mode:
        self.asked.append((user_id, allocation_id))
        return self.by_allocation.get(allocation_id, self.mode)


@dataclass
class AnyKeyTrades:
    """``TradeCapabilityPort`` for tests that are not about the key: every exchange
    answers ``answer``. ``asked`` records the ``(user, exchange)`` of each call and
    ``events`` is shared with the fakes around it, so a test can prove the read came
    after the lock, or never happened."""

    answer: TradeCapability = TradeCapability.TRADE_CAPABLE
    asked: list[tuple[UUID, str]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    async def capability(self, user_id: UUID, exchange: str) -> TradeCapability:
        self.asked.append((user_id, exchange))
        self.events.append("trade_capability")
        return self.answer

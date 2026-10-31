"""An opening of a subscription that stopped taking them (owner decision 4; tasks.md
N1, N5, E2.2).

``Leave`` counts holdings and live reservations, so an opening delivery still queued
is neither: the subscription ends, and the delivery would then open a position no
close reaches. Once this allocation holds the pool lock it reads the subscription,
and anything but ``ACTIVE`` reserves nothing. The skip is an ordinary outcome of a
user's own action, so it is an INFO and not a WARNING.

The real-PostgreSQL proof, in both orders against ``Leave``, lives in
``tests/subscriptions/application/test_leave_vs_opening_concurrency.py``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
)
from strategy_manager.allocation.application.ports import PoolBalance
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Money
from tests.allocation.application.test_allocate_capital import (
    FakePoolBalancePort,
    FakeReservationRepository,
    FakeStrategyPolicyPort,
    FrozenClock,
    _enabled_snapshot,
)
from tests.allocation.fakes import (
    ActiveSubscription,
    AlwaysEnabledPool,
    AnyKeyTrades,
    FixedUserMode,
    RecordingSkipRecorder,
)
from tests.owner import OWNER_ID


class _EventLock:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def acquire(self, key: LockKey) -> None:
        self._events.append("lock")


class _EventCommit:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def commit(self) -> None:
        self._events.append("commit")


@dataclass
class _Rig:
    use_case: AllocateCapital
    strategy_id: UUID
    subscription: ActiveSubscription
    reservations: FakeReservationRepository
    recorder: RecordingSkipRecorder
    events: list[str]

    def command(self, signal_id: UUID, delivery_id: UUID) -> AllocateCommand:
        return AllocateCommand(
            signal_id=signal_id,
            strategy_id=self.strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            user_id=OWNER_ID,
            delivery_id=delivery_id,
            pre_checked_mode=Mode.LIVE,
        )


def _rig(*, active: bool) -> _Rig:
    events: list[str] = []
    strategy_id = uuid4()
    subscription = ActiveSubscription(active=active, events=events)
    reservations = FakeReservationRepository()
    recorder = RecordingSkipRecorder()
    use_case = AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(_enabled_snapshot(strategy_id=strategy_id)),
        pool_balance=FakePoolBalancePort(
            PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("10")
            )
        ),
        lock=_EventLock(events),
        reservations=reservations,
        commit=_EventCommit(events),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
        skip_recorder=recorder,
        pool_status=AlwaysEnabledPool(),
        user_mode=FixedUserMode(),
        trade_capability=AnyKeyTrades(),
        subscription_state=subscription,
    )
    return _Rig(use_case, strategy_id, subscription, reservations, recorder, events)


async def test_a_subscription_that_left_reserves_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _rig(active=False)
    signal_id, delivery_id = uuid4(), uuid4()

    with caplog.at_level("INFO"):
        result = await rig.use_case.allocate(rig.command(signal_id, delivery_id))

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "SUBSCRIPTION_NOT_ACTIVE"
    assert result.granted == Decimal("0")
    assert result.reservation_id is None
    assert rig.reservations.inserted == []
    assert rig.subscription.asked == [delivery_id]

    lines = [r for r in caplog.records if "SUBSCRIPTION_NOT_ACTIVE" in r.getMessage()]
    assert [r.levelname for r in lines] == ["INFO"]
    message = lines[0].getMessage()
    assert str(signal_id) in message
    assert str(delivery_id) in message
    assert str(rig.strategy_id) in message
    assert "no capital reserved" in message
    assert rig.recorder.calls == [(delivery_id, "SUBSCRIPTION_NOT_ACTIVE", message)]


async def test_an_active_subscription_opens_as_before() -> None:
    rig = _rig(active=True)
    delivery_id = uuid4()

    result = await rig.use_case.allocate(rig.command(uuid4(), delivery_id))

    assert result.outcome is not DecisionOutcome.SKIP
    assert result.reservation_id is not None
    assert len(rig.reservations.inserted) == 1
    assert rig.subscription.asked == [delivery_id]
    assert rig.recorder.calls == []


async def test_the_subscription_is_read_after_the_lock_and_before_the_commit() -> None:
    rig = _rig(active=False)

    await rig.use_case.allocate(rig.command(uuid4(), uuid4()))

    assert rig.events == ["lock", "subscription_state", "commit"]


async def test_a_resumed_reservation_never_asks() -> None:
    """A retry of an opening that already reserved was on its way before any leave:
    ``Leave`` saw that reservation and made the subscription ``LEAVING``, so it runs."""
    rig = _rig(active=True)
    signal_id, delivery_id = uuid4(), uuid4()
    first = await rig.use_case.allocate(rig.command(signal_id, delivery_id))
    rig.reservations.existing = rig.reservations.inserted[0]
    rig.subscription.active = False
    rig.subscription.asked.clear()

    again = await rig.use_case.allocate(rig.command(signal_id, delivery_id))

    assert again.reservation_id == first.reservation_id
    assert again.outcome is not DecisionOutcome.SKIP
    assert rig.subscription.asked == []

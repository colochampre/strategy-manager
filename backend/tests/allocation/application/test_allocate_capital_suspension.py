"""An opening for a suspended account, or on a suspended author's strategy, reserves
nothing once the pool lock is held (public-site LS9, PS.13 S3 and S4).

Both are read in the lock because a suspension can land after ``ProcessDelivery``'s plain
reads. The outcome is a recorded skip, never a raise: a retry would only be refused again.
The real-PostgreSQL proof against ``SuspendAccount`` is in
``tests/identity/application/test_suspend_account_fence.py``.
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
    reservations: FakeReservationRepository
    recorder: RecordingSkipRecorder
    events: list[str]

    def command(self, delivery_id: UUID) -> AllocateCommand:
        return AllocateCommand(
            signal_id=uuid4(),
            strategy_id=self.strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            user_id=OWNER_ID,
            delivery_id=delivery_id,
            pre_checked_mode=Mode.LIVE,
        )


def _rig(*, account_suspended: bool = False, author_suspended: bool = False) -> _Rig:
    events: list[str] = []
    strategy_id = uuid4()
    reservations = FakeReservationRepository()
    recorder = RecordingSkipRecorder()
    use_case = AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(
            _enabled_snapshot(strategy_id=strategy_id, author_suspended=author_suspended)
        ),
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
        user_mode=FixedUserMode(
            events=events, suspended=account_suspended, track_suspension=True
        ),
        trade_capability=AnyKeyTrades(),
        subscription_state=ActiveSubscription(events=events),
    )
    return _Rig(use_case, strategy_id, reservations, recorder, events)


async def test_a_suspended_account_reserves_nothing_and_records_the_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _rig(account_suspended=True)
    delivery_id = uuid4()

    with caplog.at_level("WARNING"):
        result = await rig.use_case.allocate(rig.command(delivery_id))

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "ACCOUNT_SUSPENDED"
    assert result.granted == Decimal("0") and result.reservation_id is None
    assert rig.reservations.inserted == []
    [call] = rig.recorder.calls
    assert call[:2] == (delivery_id, "ACCOUNT_SUSPENDED")
    assert [r.levelname for r in caplog.records if "ACCOUNT_SUSPENDED" in r.getMessage()] == [
        "WARNING"
    ]
    assert "no capital reserved" in call[2]


async def test_the_suspension_is_read_after_the_lock_on_the_locked_user_row_then_committed() -> (
    None
):
    rig = _rig(account_suspended=True)

    await rig.use_case.allocate(rig.command(uuid4()))

    assert rig.events == ["lock", "user_mode", "user_suspended", "commit"]


async def test_a_suspension_landing_before_the_lock_is_a_skip_not_a_raise() -> None:
    rig = _rig()
    rig.use_case._user_mode = FixedUserMode(  # type: ignore[attr-defined]
        events=rig.events, suspended=False, suspended_in_lock=True
    )

    result = await rig.use_case.allocate(rig.command(uuid4()))

    assert result.skip_reason == "ACCOUNT_SUSPENDED"
    assert rig.reservations.inserted == []


async def test_a_suspended_authors_strategy_reserves_nothing_and_records_the_skip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _rig(author_suspended=True)
    delivery_id = uuid4()

    with caplog.at_level("WARNING"):
        result = await rig.use_case.allocate(rig.command(delivery_id))

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "AUTHOR_SUSPENDED"
    assert result.reservation_id is None
    assert rig.reservations.inserted == []
    [call] = rig.recorder.calls
    assert call[:2] == (delivery_id, "AUTHOR_SUSPENDED")
    assert [r.levelname for r in caplog.records if "AUTHOR_SUSPENDED" in r.getMessage()] == [
        "WARNING"
    ]
    assert rig.events[-1] == "commit"


async def test_nobody_suspended_opens_as_before() -> None:
    rig = _rig()

    result = await rig.use_case.allocate(rig.command(uuid4()))

    assert result.outcome is not DecisionOutcome.SKIP
    assert len(rig.reservations.inserted) == 1
    assert rig.recorder.calls == []

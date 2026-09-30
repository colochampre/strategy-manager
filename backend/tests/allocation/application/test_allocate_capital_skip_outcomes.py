"""Decision 25, tasks 5b.5: every skip ``AllocateCapital`` produces (row 8 of
the outcome map) is handed to the ``SkipRecorderPort`` with the existing
``skip_reason`` value and the human message already logged for it, staged
immediately BEFORE the commit that makes the skip durable (design.md
"Addendum: signal outcomes" § C).

The pre-lock ``STRATEGY_DISABLED`` skip had no commit of its own; this pins
the one added for it.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
)
from strategy_manager.allocation.application.ports import PoolBalance, StrategyPolicySnapshot
from strategy_manager.shared.domain.money import Currency, Money
from tests.allocation.application.test_allocate_capital import (
    FakeAdvisoryLock,
    FakePoolBalancePort,
    FakeReservationRepository,
    FakeStrategyPolicyPort,
    FrozenClock,
    SequencedStrategyPolicyPort,
    _enabled_snapshot,
)
from tests.allocation.fakes import AlwaysEnabledPool, RecordingSkipRecorder


@dataclass
class OrderingCommit:
    """Records how many skips were already staged at each commit."""

    recorder: RecordingSkipRecorder
    staged_at_commit: list[int] = field(default_factory=list)

    async def commit(self) -> None:
        self.staged_at_commit.append(len(self.recorder.calls))


def _use_case(
    policy: FakeStrategyPolicyPort | SequencedStrategyPolicyPort,
    pool_balance: PoolBalance | None,
    recorder: RecordingSkipRecorder,
    commit: OrderingCommit,
    lock: FakeAdvisoryLock | None = None,
) -> AllocateCapital:
    return AllocateCapital(
        strategy_policy=policy,
        pool_balance=FakePoolBalancePort(pool_balance),
        lock=lock or FakeAdvisoryLock(),
        reservations=FakeReservationRepository(),
        commit=commit,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
        skip_recorder=recorder,
        pool_status=AlwaysEnabledPool(),
    )


def _command(signal_id: object, strategy_id: object) -> AllocateCommand:
    return AllocateCommand(
        signal_id=signal_id,  # type: ignore[arg-type]
        strategy_id=strategy_id,  # type: ignore[arg-type]
        requested=Money(amount=Decimal("200"), currency=Currency.USDT),
    )


def _pool(total: str, available: str, minimum: str) -> PoolBalance:
    return PoolBalance(
        total=Decimal(total), available=Decimal(available), min_order_size=Decimal(minimum)
    )


async def test_pre_lock_disabled_skip_records_the_reason_and_adds_its_own_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal_id, strategy_id = uuid4(), uuid4()
    recorder = RecordingSkipRecorder()
    commit = OrderingCommit(recorder)
    lock = FakeAdvisoryLock()
    use_case = _use_case(
        FakeStrategyPolicyPort(_enabled_snapshot(strategy_id=strategy_id, enabled=False)),
        None,
        recorder,
        commit,
        lock,
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(_command(signal_id, strategy_id))

    assert result.skip_reason == "STRATEGY_DISABLED"
    assert lock.acquired == []  # still pre-lock: the commit added holds no lock
    message = next(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert recorder.calls == [(signal_id, "STRATEGY_DISABLED", message)]
    assert commit.staged_at_commit == [1]


@pytest.mark.parametrize(
    ("second", "reason"),
    [
        (dict(enabled=False, archived=False), "STRATEGY_DISABLED"),
        (dict(enabled=False, archived=True), "STRATEGY_ARCHIVED"),
    ],
)
async def test_in_lock_skip_records_the_reason_before_its_existing_commit(
    caplog: pytest.LogCaptureFixture, second: dict[str, bool], reason: str
) -> None:
    signal_id, strategy_id = uuid4(), uuid4()
    recorder = RecordingSkipRecorder()
    commit = OrderingCommit(recorder)
    policy = SequencedStrategyPolicyPort(
        snapshots=[
            _enabled_snapshot(strategy_id=strategy_id, enabled=True),
            _enabled_snapshot(strategy_id=strategy_id, **second),
        ]
    )
    use_case = _use_case(policy, _pool("1000", "1000", "10"), recorder, commit)

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(_command(signal_id, strategy_id))

    assert result.skip_reason == reason
    message = next(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert recorder.calls == [(signal_id, reason, message)]
    assert commit.staged_at_commit == [1]


@pytest.mark.parametrize(
    ("overrides", "pool", "reason"),
    [
        ({}, _pool("0", "0", "10"), "NO_AVAILABILITY"),
        ({"fill_mode": "SKIP"}, _pool("50", "50", "10"), "INSUFFICIENT_AVAILABILITY"),
        ({}, _pool("1000", "1000", "300"), "REQUEST_BELOW_MIN_ORDER_SIZE"),
        ({}, _pool("1000", "5", "10"), "PARTIAL_BELOW_MIN_ORDER_SIZE"),
    ],
)
async def test_decide_skip_records_the_engine_reason_before_the_commit(
    caplog: pytest.LogCaptureFixture,
    overrides: dict[str, str],
    pool: PoolBalance,
    reason: str,
) -> None:
    signal_id, strategy_id = uuid4(), uuid4()
    recorder = RecordingSkipRecorder()
    commit = OrderingCommit(recorder)
    snapshot: StrategyPolicySnapshot = _enabled_snapshot(strategy_id=strategy_id, **overrides)
    use_case = _use_case(FakeStrategyPolicyPort(snapshot), pool, recorder, commit)

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(_command(signal_id, strategy_id))

    assert result.skip_reason == reason
    message = next(r.getMessage() for r in caplog.records if r.levelname == "WARNING")
    assert recorder.calls == [(signal_id, reason, message)]
    assert commit.staged_at_commit == [1]


async def test_a_granted_allocation_records_no_skip() -> None:
    signal_id, strategy_id = uuid4(), uuid4()
    recorder = RecordingSkipRecorder()
    commit = OrderingCommit(recorder)
    use_case = _use_case(
        FakeStrategyPolicyPort(_enabled_snapshot(strategy_id=strategy_id)),
        _pool("1000", "1000", "10"),
        recorder,
        commit,
    )

    result = await use_case.allocate(_command(signal_id, strategy_id))

    assert result.reservation_id is not None
    assert recorder.calls == []
    assert commit.staged_at_commit == [0]

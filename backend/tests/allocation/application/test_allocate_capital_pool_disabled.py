"""W1 of the independent verification of PR 8b-2: a pool disabled while an
allocation waited for its advisory lock.

``DeleteCredential`` deactivates the key and disables the pool under the pool
lock. An allocation that passed its pre-lock checks BEFORE that and then waited
for the lock must, once it holds it, re-read whether the pool is still enabled:
otherwise it reserves capital on a keyless exchange and the reservation sits
until its TTL. The skip is distinct (``POOL_DISABLED``), logged, recorded as the
signal's outcome (decision 25), and reserves nothing.

The real-PostgreSQL proof that the read happens AFTER the lock lives in
``tests/accounts/application/test_allocate_pool_disabled_integration.py``.
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
from strategy_manager.shared.domain.money import Currency, Money
from tests.allocation.application.test_allocate_capital import (
    FakePoolBalancePort,
    FakeReservationRepository,
    FakeStrategyPolicyPort,
    FrozenClock,
    _enabled_snapshot,
)
from tests.allocation.fakes import RecordingPoolStatus, RecordingSkipRecorder


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
    pool_status: RecordingPoolStatus
    reservations: FakeReservationRepository
    recorder: RecordingSkipRecorder

    def command(self, signal_id: UUID) -> AllocateCommand:
        return AllocateCommand(
            signal_id=signal_id,
            strategy_id=self.strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )


def _rig(*, disabled: bool) -> _Rig:
    events: list[str] = []
    strategy_id = uuid4()
    pool_status = RecordingPoolStatus(disabled=disabled, events=events)
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
        pool_status=pool_status,
    )
    return _Rig(use_case, strategy_id, pool_status, reservations, recorder)


async def test_an_enabled_strategy_on_a_pool_disabled_in_the_lock_skips_and_reserves_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _rig(disabled=True)
    signal_id = uuid4()

    with caplog.at_level("WARNING"):
        result = await rig.use_case.allocate(rig.command(signal_id))

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "POOL_DISABLED"
    assert result.granted == Decimal("0")
    assert result.reservation_id is None
    assert rig.reservations.inserted == []

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0]
    assert str(rig.strategy_id) in warnings[0]
    assert "pionex/spot/USDT" in warnings[0]
    assert "no capital reserved" in warnings[0]
    assert "POOL_DISABLED" in warnings[0]

    assert rig.recorder.calls == [(signal_id, "POOL_DISABLED", warnings[0])]
    assert rig.pool_status.calls == [("pionex", "spot", "USDT")]


async def test_the_pool_is_read_after_the_lock_and_the_skip_is_staged_before_the_commit() -> None:
    rig = _rig(disabled=True)

    await rig.use_case.allocate(rig.command(uuid4()))

    assert rig.pool_status.events == ["lock", "pool_status", "commit"]


async def test_an_enabled_pool_changes_nothing_and_still_reserves(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _rig(disabled=False)

    with caplog.at_level("WARNING"):
        result = await rig.use_case.allocate(rig.command(uuid4()))

    assert result.reservation_id is not None
    assert result.skip_reason is None
    assert len(rig.reservations.inserted) == 1
    assert rig.recorder.calls == []
    assert [r for r in caplog.records if r.levelname == "WARNING"] == []
    assert len(rig.pool_status.calls) == 1

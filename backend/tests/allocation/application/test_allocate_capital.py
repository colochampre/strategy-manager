"""Unit tests for ``AllocateCapital`` pre-lock guards — resume without lock,
disabled-strategy skip without lock, unknown pool raises, currency mismatch,
non-positive request — using fake ports and a ``FrozenClock`` (tasks.md 4.7).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.allocation.application.allocate_capital import (
    AllocateCapital,
    AllocateCommand,
    CurrencyMismatchError,
    InvalidAllocationRequestError,
    UnknownPoolError,
)
from strategy_manager.allocation.application.ports import PoolBalance, StrategyPolicySnapshot
from strategy_manager.allocation.domain.decision import DecisionOutcome
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.money import Currency, Money, Venue


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass
class FakeStrategyPolicyPort:
    snapshot: StrategyPolicySnapshot

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        return self.snapshot


@dataclass
class FakePoolBalancePort:
    balance: PoolBalance | None = None

    async def read(self, venue: str, settlement_currency: str) -> PoolBalance:
        if self.balance is None:
            raise InvariantViolation(f"no configured pool for ({venue}, {settlement_currency})")
        return self.balance


@dataclass
class FakeAdvisoryLock:
    acquired: list[LockKey] = field(default_factory=list)

    async def acquire(self, key: LockKey) -> None:
        self.acquired.append(key)


@dataclass
class FakeReservationRepository:
    existing: Reservation | None = None
    inserted: list[Reservation] = field(default_factory=list)
    sum_active_return: Decimal = Decimal("0")

    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None:
        return self.existing

    async def sum_active(self, venue: str, settlement_currency: str, now: datetime) -> Decimal:
        return self.sum_active_return

    async def insert(self, reservation: Reservation) -> None:
        self.inserted.append(reservation)

    async def mark(self, reservation_id: UUID, status: ReservationStatus, at: datetime) -> None:
        raise NotImplementedError


@dataclass
class FakeCommit:
    committed: bool = False

    async def commit(self) -> None:
        self.committed = True


def _enabled_snapshot(**overrides: object) -> StrategyPolicySnapshot:
    defaults: dict[str, object] = dict(
        strategy_id=uuid4(),
        enabled=True,
        fill_mode="PARTIAL",
        venue="spot",
        settlement_currency="USDT",
    )
    defaults.update(overrides)
    return StrategyPolicySnapshot(**defaults)  # type: ignore[arg-type]


def _build_use_case(
    *,
    policy: StrategyPolicySnapshot,
    pool_balance: PoolBalance | None,
    reservations: FakeReservationRepository | None = None,
    lock: FakeAdvisoryLock | None = None,
    commit: FakeCommit | None = None,
) -> tuple[AllocateCapital, FakeAdvisoryLock, FakeReservationRepository, FakeCommit]:
    lock = lock or FakeAdvisoryLock()
    reservations = reservations or FakeReservationRepository()
    commit = commit or FakeCommit()
    use_case = AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(policy),
        pool_balance=FakePoolBalancePort(pool_balance),
        lock=lock,
        reservations=reservations,
        commit=commit,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
    )
    return use_case, lock, reservations, commit


async def test_resume_returns_existing_reservation_without_taking_the_lock() -> None:
    existing = Reservation(
        id=uuid4(),
        strategy_id=uuid4(),
        signal_id=uuid4(),
        pool_key=PoolKey(venue=Venue.SPOT, settlement_currency=Currency.USDT),
        amount=Decimal("200"),
        status=ReservationStatus.PENDING,
        expires_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=30),
    )
    reservations = FakeReservationRepository(existing=existing)
    use_case, lock, _, commit = _build_use_case(
        policy=_enabled_snapshot(), pool_balance=None, reservations=reservations
    )

    result = await use_case.allocate(
        AllocateCommand(
            signal_id=existing.signal_id,
            strategy_id=existing.strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )
    )

    assert result.resumed is True
    assert result.reservation_id == existing.id
    assert result.granted == Decimal("200")
    assert lock.acquired == []
    assert commit.committed is False


async def test_disabled_strategy_skips_without_taking_the_lock() -> None:
    use_case, lock, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(enabled=False), pool_balance=None
    )

    result = await use_case.allocate(
        AllocateCommand(
            signal_id=uuid4(),
            strategy_id=uuid4(),
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )
    )

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "STRATEGY_DISABLED"
    assert result.reservation_id is None
    assert lock.acquired == []
    assert reservations.inserted == []


async def test_unknown_pool_raises() -> None:
    use_case, _, _, _ = _build_use_case(policy=_enabled_snapshot(), pool_balance=None)

    with pytest.raises(UnknownPoolError):
        await use_case.allocate(
            AllocateCommand(
                signal_id=uuid4(),
                strategy_id=uuid4(),
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )


async def test_currency_mismatch_raises() -> None:
    use_case, lock, _, _ = _build_use_case(
        policy=_enabled_snapshot(settlement_currency="USDT"),
        pool_balance=PoolBalance(balance=Decimal("1000"), min_order_size=Decimal("10")),
    )

    with pytest.raises(CurrencyMismatchError):
        await use_case.allocate(
            AllocateCommand(
                signal_id=uuid4(),
                strategy_id=uuid4(),
                requested=Money(amount=Decimal("200"), currency=Currency.BTC),
            )
        )

    assert lock.acquired == []  # a pure/local check does not deserve lock hold time


async def test_non_positive_request_raises() -> None:
    use_case, lock, _, _ = _build_use_case(
        policy=_enabled_snapshot(),
        pool_balance=PoolBalance(balance=Decimal("1000"), min_order_size=Decimal("10")),
    )

    with pytest.raises(InvalidAllocationRequestError):
        await use_case.allocate(
            AllocateCommand(
                signal_id=uuid4(),
                strategy_id=uuid4(),
                requested=Money(amount=Decimal("0"), currency=Currency.USDT),
            )
        )

    assert lock.acquired == []


async def test_full_allocation_takes_the_lock_writes_a_reservation_and_commits() -> None:
    strategy_id = uuid4()
    use_case, lock, reservations, commit = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id),
        pool_balance=PoolBalance(balance=Decimal("1000"), min_order_size=Decimal("10")),
    )

    result = await use_case.allocate(
        AllocateCommand(
            signal_id=uuid4(),
            strategy_id=strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )
    )

    assert result.outcome is DecisionOutcome.FULL
    assert result.granted == Decimal("200")
    assert result.reservation_id is not None
    assert len(lock.acquired) == 1
    assert lock.acquired[0] == LockKey(venue="spot", settlement_currency="USDT")
    assert len(reservations.inserted) == 1
    assert reservations.inserted[0].amount == Decimal("200")
    assert commit.committed is True

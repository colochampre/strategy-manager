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
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from tests.allocation.fakes import RecordingSkipRecorder


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
class SequencedStrategyPolicyPort:
    """Answers a DIFFERENT snapshot on each successive call -- what proves
    the in-lock re-check (design.md § 8 point (ii)) genuinely re-reads
    rather than reusing the pre-lock policy it already has in hand. A
    ``FakeStrategyPolicyPort`` returning one fixed snapshot cannot
    distinguish "read once" from "read twice, same answer" -- this fake
    can, by answering enabled the first time and disabled/archived the
    second."""

    snapshots: list[StrategyPolicySnapshot]
    calls: int = 0

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        snapshot = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        return snapshot


@dataclass
class FakePoolBalancePort:
    balance: PoolBalance | None = None

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolBalance:
        if self.balance is None:
            raise InvariantViolation(
                f"no configured pool for ({exchange}, {venue}, {settlement_currency})"
            )
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

    async def sum_active(
        self, exchange: str, venue: str, settlement_currency: str, now: datetime
    ) -> Decimal:
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
        allocation_percent=Decimal("100"),
    )
    defaults.update(overrides)
    # Pionex, because the default venue is spot: the lock key these tests
    # assert on is built from both, so a mismatched pair would compare unequal
    # for a reason that has nothing to do with what is being tested.
    return StrategyPolicySnapshot(exchange=Exchange.PIONEX, **defaults)  # type: ignore[arg-type]


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
        skip_recorder=RecordingSkipRecorder(),
    )
    return use_case, lock, reservations, commit


async def test_resume_returns_existing_reservation_without_taking_the_lock() -> None:
    existing = Reservation(
        id=uuid4(),
        strategy_id=uuid4(),
        signal_id=uuid4(),
        pool_key=PoolKey(
            exchange=Exchange.PIONEX,
            venue=Venue.SPOT,
            settlement_currency=Currency.USDT,
        ),
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
        pool_balance=PoolBalance(
            total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("10")
        ),
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
        pool_balance=PoolBalance(
            total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("10")
        ),
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
        pool_balance=PoolBalance(
            total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("10")
        ),
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
    assert lock.acquired[0] == LockKey(exchange="pionex", venue="spot", settlement_currency="USDT")
    assert len(reservations.inserted) == 1
    assert reservations.inserted[0].amount == Decimal("200")
    assert commit.committed is True


# --------------------------------------------------------------------------
# 2c.10 -- the in-lock re-check (design.md § 8 point (ii))
# --------------------------------------------------------------------------


async def test_in_lock_reread_skips_with_strategy_disabled_when_disabled_after_prelock_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The pre-lock read sees ``enabled=True`` (so the pre-lock guard lets
    it through and the lock is taken); the IN-LOCK re-read then sees
    ``enabled=False`` -- exactly what a concurrent ``UpdateStrategy``
    committing between the two reads would produce. The allocation must
    skip WITHOUT writing a reservation, and log exactly one WARNING naming
    the strategy and the signal (binding requirement 4 -- this is the ONLY
    record of the refusal, since ``signals.status`` never leaves ACCEPTED)."""
    strategy_id = uuid4()
    signal_id = uuid4()
    policy = SequencedStrategyPolicyPort(
        snapshots=[
            _enabled_snapshot(strategy_id=strategy_id, enabled=True),
            _enabled_snapshot(strategy_id=strategy_id, enabled=False),
        ]
    )
    lock = FakeAdvisoryLock()
    reservations = FakeReservationRepository()
    commit = FakeCommit()
    use_case = AllocateCapital(
        strategy_policy=policy,  # type: ignore[arg-type]
        pool_balance=FakePoolBalancePort(
            PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("10")
            )
        ),
        lock=lock,
        reservations=reservations,
        commit=commit,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert policy.calls == 2  # pre-lock AND in-lock -- proves the re-read happened
    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "STRATEGY_DISABLED"
    assert result.reservation_id is None
    assert reservations.inserted == []  # no reservation ever written
    assert len(lock.acquired) == 1  # the lock WAS taken (pre-lock guard passed)
    assert commit.committed is True  # released via commit, not left hanging

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0].getMessage()
    assert str(strategy_id) in warnings[0].getMessage()
    assert "STRATEGY_DISABLED" in warnings[0].getMessage()


async def test_in_lock_reread_skips_with_strategy_archived_when_archived_after_prelock_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same race, the other closing half (design.md § 8, "archive wins the
    lock first"): the pre-lock read still sees ``enabled=True`` (an
    archived strategy is always disabled too, but the pre-lock guard only
    checked ``enabled`` before this strategy was archived), and the in-lock
    re-read sees ``archived=True`` -- distinct skip reason, one WARNING."""
    strategy_id = uuid4()
    signal_id = uuid4()
    policy = SequencedStrategyPolicyPort(
        snapshots=[
            _enabled_snapshot(strategy_id=strategy_id, enabled=True, archived=False),
            _enabled_snapshot(strategy_id=strategy_id, enabled=False, archived=True),
        ]
    )
    lock = FakeAdvisoryLock()
    reservations = FakeReservationRepository()
    commit = FakeCommit()
    use_case = AllocateCapital(
        strategy_policy=policy,  # type: ignore[arg-type]
        pool_balance=FakePoolBalancePort(
            PoolBalance(
                total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("10")
            )
        ),
        lock=lock,
        reservations=reservations,
        commit=commit,
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert policy.calls == 2
    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "STRATEGY_ARCHIVED"
    assert result.reservation_id is None
    assert reservations.inserted == []
    assert commit.committed is True

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0].getMessage()
    assert str(strategy_id) in warnings[0].getMessage()
    assert "STRATEGY_ARCHIVED" in warnings[0].getMessage()


# --------------------------------------------------------------------------
# 2f.1 -- a log line on every SKIP `AllocateCapital` produces that is not
# already covered by 2c's in-lock re-check WARNING above (orchestrator's
# outcome map, finding 8: ``process_signal.py`` drops every one of these at
# ``result.reservation_id is None``, with no log at all).
# --------------------------------------------------------------------------


async def test_pre_lock_disabled_skip_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The PRE-lock disabled skip (``policy.enabled`` false before the lock
    is ever taken) -- distinct from 2c's IN-lock re-check WARNING, which
    only fires once the lock is already held. This is the only trace of a
    signal for an already-disabled strategy today."""
    signal_id = uuid4()
    strategy_id = uuid4()
    use_case, lock, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id, enabled=False), pool_balance=None
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.skip_reason == "STRATEGY_DISABLED"
    assert lock.acquired == []  # pre-lock: never reached the lock at all
    assert reservations.inserted == []

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0].getMessage()
    assert str(strategy_id) in warnings[0].getMessage()
    assert "STRATEGY_DISABLED" in warnings[0].getMessage()


async def test_decide_skip_no_availability_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``decide()`` Rule 2: the pool is empty. Skipped inside the lock, after
    the in-lock re-check already passed -- a different WARNING from 2c's,
    since this one comes from the ENGINE's own decision, not a lifecycle
    re-check."""
    signal_id = uuid4()
    strategy_id = uuid4()
    use_case, lock, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id),
        pool_balance=PoolBalance(
            total=Decimal("0"), available=Decimal("0"), min_order_size=Decimal("10")
        ),
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "NO_AVAILABILITY"
    assert len(lock.acquired) == 1  # this skip only happens INSIDE the lock
    assert reservations.inserted == []

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0].getMessage()
    assert str(strategy_id) in warnings[0].getMessage()
    assert "NO_AVAILABILITY" in warnings[0].getMessage()


async def test_decide_skip_insufficient_availability_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``decide()`` Rule 4: available > 0 but below the request, and
    ``fill_mode`` is SKIP rather than PARTIAL."""
    signal_id = uuid4()
    strategy_id = uuid4()
    use_case, lock, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id, fill_mode="SKIP"),
        pool_balance=PoolBalance(
            total=Decimal("50"), available=Decimal("50"), min_order_size=Decimal("10")
        ),
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "INSUFFICIENT_AVAILABILITY"
    assert len(lock.acquired) == 1
    assert reservations.inserted == []

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0].getMessage()
    assert str(strategy_id) in warnings[0].getMessage()
    assert "INSUFFICIENT_AVAILABILITY" in warnings[0].getMessage()


async def test_decide_skip_below_min_order_size_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``decide()`` Rule 1: the request itself is below the pool's minimum
    order size -- refused before availability is even read."""
    signal_id = uuid4()
    strategy_id = uuid4()
    use_case, lock, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id),
        pool_balance=PoolBalance(
            total=Decimal("1000"), available=Decimal("1000"), min_order_size=Decimal("300")
        ),
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.outcome is DecisionOutcome.SKIP
    assert result.skip_reason == "REQUEST_BELOW_MIN_ORDER_SIZE"
    assert len(lock.acquired) == 1
    assert reservations.inserted == []

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(signal_id) in warnings[0].getMessage()
    assert str(strategy_id) in warnings[0].getMessage()
    assert "REQUEST_BELOW_MIN_ORDER_SIZE" in warnings[0].getMessage()


# --------------------------------------------------------------------------
# 3a.2 / 3a.4 -- ``pool_total_at_open`` (design.md section 10, finding F1):
# the pool capital recorded on a reservation is the read made INSIDE the lock.
# --------------------------------------------------------------------------


@dataclass
class LockAwarePoolBalancePort:
    """Answers ``before_lock`` until the advisory lock is held and
    ``inside_lock`` afterwards, and counts every read. What lets a test tell
    the pre-lock sizing read from the in-lock read that ``AllocateCapital``
    already makes, and prove no third read was added."""

    lock: FakeAdvisoryLock
    before_lock: PoolBalance
    inside_lock: PoolBalance
    reads: int = 0

    async def read(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> PoolBalance:
        self.reads += 1
        return self.inside_lock if self.lock.acquired else self.before_lock


async def test_reservation_records_in_lock_pool_capital_not_prelock_read() -> None:
    strategy_id = uuid4()
    lock = FakeAdvisoryLock()
    balance = LockAwarePoolBalancePort(
        lock=lock,
        before_lock=PoolBalance(
            total=Decimal("510"), available=Decimal("510"), min_order_size=Decimal("10")
        ),
        inside_lock=PoolBalance(
            total=Decimal("500"), available=Decimal("500"), min_order_size=Decimal("10")
        ),
    )
    reservations = FakeReservationRepository()
    use_case = AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(_enabled_snapshot(strategy_id=strategy_id)),
        pool_balance=balance,
        lock=lock,
        reservations=reservations,
        commit=FakeCommit(),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
    )

    result = await use_case.allocate(
        AllocateCommand(
            signal_id=uuid4(),
            strategy_id=strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )
    )

    assert result.outcome is DecisionOutcome.FULL
    assert len(reservations.inserted) == 1
    assert reservations.inserted[0].pool_total_at_open == Decimal("500")
    assert balance.reads == 1  # the existing in-lock read; none was added


async def test_reservation_records_the_total_not_the_available_of_the_pool() -> None:
    """``total`` is the pool's capital; ``available`` is what is left to grant.
    A pool with 300 committed elsewhere has total 1000 and available 700, and
    the reservation must record the 1000."""
    strategy_id = uuid4()
    use_case, _, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id),
        pool_balance=PoolBalance(
            total=Decimal("1000"), available=Decimal("700"), min_order_size=Decimal("10")
        ),
    )

    await use_case.allocate(
        AllocateCommand(
            signal_id=uuid4(),
            strategy_id=strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )
    )

    assert reservations.inserted[0].amount == Decimal("200")
    assert reservations.inserted[0].pool_total_at_open == Decimal("1000")


async def test_a_pool_total_of_zero_is_stored_as_none_never_as_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The port does not enforce ``total >= available`` (the database does, on
    the snapshot the production source reads). A source that broke it would
    otherwise hand the insert a value the ``> 0`` CHECK refuses, failing an
    allocation that ``decide()`` granted. NULL says "unknown" and the trade
    is merely left out of the curve; a zero would abort the allocation."""
    strategy_id = uuid4()
    use_case, _, reservations, _ = _build_use_case(
        policy=_enabled_snapshot(strategy_id=strategy_id),
        pool_balance=PoolBalance(
            total=Decimal("0"), available=Decimal("1000"), min_order_size=Decimal("10")
        ),
    )

    with caplog.at_level("WARNING"):
        result = await use_case.allocate(
            AllocateCommand(
                signal_id=uuid4(),
                strategy_id=strategy_id,
                requested=Money(amount=Decimal("200"), currency=Currency.USDT),
            )
        )

    assert result.outcome is DecisionOutcome.FULL
    assert reservations.inserted[0].pool_total_at_open is None
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert str(strategy_id) in warnings[0].getMessage()
    assert "pool_total_at_open" in warnings[0].getMessage()


async def test_resume_of_retried_allocation_returns_existing_row_unchanged() -> None:
    signal_id = uuid4()
    strategy_id = uuid4()
    existing = Reservation(
        id=uuid4(),
        strategy_id=strategy_id,
        signal_id=signal_id,
        pool_key=PoolKey(
            exchange=Exchange.PIONEX, venue=Venue.SPOT, settlement_currency=Currency.USDT
        ),
        amount=Decimal("200"),
        status=ReservationStatus.PENDING,
        expires_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=30),
        pool_total_at_open=Decimal("500"),
    )
    reservations = FakeReservationRepository(existing=existing)
    lock = FakeAdvisoryLock()
    # The pool has since grown to 900; a resume that re-read it would see that.
    balance = LockAwarePoolBalancePort(
        lock=lock,
        before_lock=PoolBalance(
            total=Decimal("900"), available=Decimal("900"), min_order_size=Decimal("10")
        ),
        inside_lock=PoolBalance(
            total=Decimal("900"), available=Decimal("900"), min_order_size=Decimal("10")
        ),
    )
    use_case = AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(_enabled_snapshot(strategy_id=strategy_id)),
        pool_balance=balance,
        lock=lock,
        reservations=reservations,
        commit=FakeCommit(),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
        skip_recorder=RecordingSkipRecorder(),
    )

    result = await use_case.allocate(
        AllocateCommand(
            signal_id=signal_id,
            strategy_id=strategy_id,
            requested=Money(amount=Decimal("200"), currency=Currency.USDT),
        )
    )

    assert result.resumed is True
    assert result.reservation_id == existing.id
    assert reservations.inserted == []  # nothing rewritten
    assert existing.pool_total_at_open == Decimal("500")
    assert balance.reads == 0  # the pool was never read again
    assert lock.acquired == []

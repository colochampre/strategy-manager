"""Unit tests: ``ProcessSignalHandler`` routes by ``PositionTransition`` — a
RELEASE-path signal (close long, close short) never acquires the advisory
lock, asserted with a spy ``AdvisoryLockPort``; a CONSUME-path signal does
acquire it (tasks.md 5.16; design.md § "position_size routes the signal").
No database: ``AllocateCapital`` is real (slice 4), wired with fakes,
including the spy lock, so the assertion exercises the actual lock call
site rather than a re-implemented stand-in.

Also covers tasks.md 7.7: a CONSUME-path signal's requested amount MUST come
from the strategy's ``allocation_percent`` applied to the pool balance,
never from the alert's ``position_size``/``contracts`` (design.md's GAP
FOUND note, closed by this slice).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.allocation.application.allocate_capital import AllocateCapital
from strategy_manager.allocation.application.ports import PoolBalance, StrategyPolicySnapshot
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.execution.application.execute_reservation import (
    ExecuteCommand,
    ExecuteResult,
)
from strategy_manager.signals.application.process_signal import (
    ProcessSignalHandler,
    SignalContext,
)


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
    balance: PoolBalance

    async def read(self, venue: str, settlement_currency: str) -> PoolBalance:
        return self.balance


@dataclass
class SpyAdvisoryLock:
    acquired: list[LockKey] = field(default_factory=list)

    async def acquire(self, key: LockKey) -> None:
        self.acquired.append(key)


@dataclass
class FakeReservationRepository:
    inserted: list[Reservation] = field(default_factory=list)

    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None:
        return None

    async def sum_active(self, venue: str, settlement_currency: str, now: datetime) -> Decimal:
        return Decimal("0")

    async def insert(self, reservation: Reservation) -> None:
        self.inserted.append(reservation)

    async def mark(self, reservation_id: UUID, status: ReservationStatus, at: datetime) -> None:
        pass


@dataclass
class FakeCommit:
    async def commit(self) -> None:
        pass


@dataclass
class SpyExecuteReservation:
    """Stands in for ``ExecuteReservation`` — records what it was asked to
    execute against, without needing an exchange/ledger stack."""

    calls: list[ExecuteCommand] = field(default_factory=list)

    async def execute(self, command: ExecuteCommand) -> ExecuteResult:
        self.calls.append(command)
        return ExecuteResult(status="FILLED", execution_attempt_id=uuid4())


@dataclass
class FakeSignalContextPort:
    context: SignalContext

    async def load(self, signal_id: UUID) -> SignalContext:
        return self.context


def _snapshot(**overrides: object) -> StrategyPolicySnapshot:
    defaults: dict[str, object] = dict(
        strategy_id=uuid4(),
        enabled=True,
        fill_mode="PARTIAL",
        venue="spot",
        settlement_currency="USDT",
        allocation_percent=Decimal("100"),
    )
    defaults.update(overrides)
    return StrategyPolicySnapshot(**defaults)  # type: ignore[arg-type]


def _allocate_capital(
    lock: SpyAdvisoryLock,
    policy: StrategyPolicySnapshot | None = None,
    pool_balance: PoolBalance | None = None,
    reservations: FakeReservationRepository | None = None,
) -> AllocateCapital:
    return AllocateCapital(
        strategy_policy=FakeStrategyPolicyPort(policy or _snapshot()),
        pool_balance=FakePoolBalancePort(
            pool_balance or PoolBalance(balance=Decimal("1000"), min_order_size=Decimal("1"))
        ),
        lock=lock,
        reservations=reservations or FakeReservationRepository(),
        commit=FakeCommit(),
        clock=FrozenClock(datetime(2026, 1, 1, tzinfo=UTC)),
        reservation_ttl_seconds=30,
    )


def _process_signal_handler(
    *,
    context: SignalContext,
    allocate_capital: AllocateCapital,
    execute_reservation: SpyExecuteReservation,
    policy: StrategyPolicySnapshot | None = None,
    pool_balance: PoolBalance | None = None,
) -> ProcessSignalHandler:
    return ProcessSignalHandler(
        signal_context=FakeSignalContextPort(context),
        strategy_policy=FakeStrategyPolicyPort(policy or _snapshot()),
        pool_balance=FakePoolBalancePort(
            pool_balance or PoolBalance(balance=Decimal("1000"), min_order_size=Decimal("1"))
        ),
        allocate_capital=allocate_capital,
        execute_reservation=execute_reservation,
    )


async def test_consumes_signal_acquires_the_advisory_lock() -> None:
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    execute_reservation = SpyExecuteReservation()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("1"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        execute_reservation=execute_reservation,
    )

    result = await handler.handle(uuid4())

    assert len(lock.acquired) == 1
    assert result.transition_kind == "open_long"
    assert len(execute_reservation.calls) == 1


async def test_releases_signal_never_acquires_the_advisory_lock() -> None:
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    execute_reservation = SpyExecuteReservation()
    prior_reservation_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # close long -> RELEASES
        prior_reservation_id=prior_reservation_id,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        execute_reservation=execute_reservation,
    )

    result = await handler.handle(uuid4())

    assert lock.acquired == []
    assert result.transition_kind == "close_long"
    assert len(execute_reservation.calls) == 1
    assert execute_reservation.calls[0].reservation_id == prior_reservation_id


async def test_releases_signal_with_no_prior_reservation_is_a_safe_no_op() -> None:
    lock = SpyAdvisoryLock()
    allocate_capital = _allocate_capital(lock)
    execute_reservation = SpyExecuteReservation()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("-1"),  # close short -> RELEASES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        execute_reservation=execute_reservation,
    )

    result = await handler.handle(uuid4())

    assert lock.acquired == []
    assert execute_reservation.calls == []
    assert result.reservation_id is None
    assert result.executed is False


async def test_consumes_signal_sizes_requested_from_allocation_percent_never_from_position_size(
) -> None:
    """tasks.md 7.7: the requested amount MUST come from the strategy's
    ``allocation_percent`` applied to the pool balance, never from the
    alert's ``position_size``/``contracts`` (design.md's GAP FOUND note,
    closed by this slice). ``position_size`` and ``price`` are set so their
    product (200,000,000) wildly differs from the percent-derived request
    (200) — if the stand-in ever regressed, this assertion would fail loudly."""
    lock = SpyAdvisoryLock()
    policy = _snapshot(allocation_percent=Decimal("20"))
    pool_balance = PoolBalance(balance=Decimal("1000"), min_order_size=Decimal("1"))
    reservations = FakeReservationRepository()
    allocate_capital = _allocate_capital(
        lock, policy=policy, pool_balance=pool_balance, reservations=reservations
    )
    execute_reservation = SpyExecuteReservation()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="BTCUSDT",
        price=Decimal("50000"),  # position_size * price = 200,000,000 - never used
        position_size=Decimal("4000"),
        prior_position_size=Decimal("0"),  # open long -> CONSUMES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=allocate_capital,
        execute_reservation=execute_reservation,
        policy=policy,
        pool_balance=pool_balance,
    )

    await handler.handle(uuid4())

    assert len(reservations.inserted) == 1
    # 20% of a 1000 balance = 200 - not 200,000,000.
    assert reservations.inserted[0].amount == Decimal("200")

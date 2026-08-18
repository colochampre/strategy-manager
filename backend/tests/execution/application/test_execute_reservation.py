"""Unit tests for ``ExecuteReservation``'s pre-submit expiry re-check — valid
submits, expired aborts to ``RELEASED`` with no submission (tasks.md 5.5;
spec: trade-execution § Pre-Submit Expiry Re-Check). Fake ``ExchangePort`` +
``FrozenClock``, no database.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.execute_reservation import (
    ExecuteCommand,
    ExecuteReservation,
)
from strategy_manager.execution.application.ports import (
    ExchangeError,
    FillRecord,
    ReservationSnapshot,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderSide


class FrozenClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


@dataclass
class FakeReservationGateway:
    reservation: ReservationSnapshot
    marked: list[tuple[UUID, str, datetime]] = field(default_factory=list)

    async def get_for_update(self, reservation_id: UUID) -> ReservationSnapshot:
        return self.reservation

    async def mark(self, reservation_id: UUID, status: str, at: datetime) -> None:
        self.marked.append((reservation_id, status, at))


@dataclass
class FakeExchange:
    fill_to_return: Fill | None = None
    error_to_raise: Exception | None = None
    submitted: list[object] = field(default_factory=list)
    is_live: bool = False

    async def submit(self, order: object) -> Fill:
        self.submitted.append(order)
        if self.error_to_raise is not None:
            raise self.error_to_raise
        assert self.fill_to_return is not None
        return self.fill_to_return


@dataclass
class FakeAttemptRepository:
    inserted: list[ExecutionAttempt] = field(default_factory=list)
    filled: list[tuple[UUID, str]] = field(default_factory=list)
    failed: list[tuple[UUID, str]] = field(default_factory=list)

    async def insert(self, attempt: ExecutionAttempt) -> None:
        self.inserted.append(attempt)

    async def mark_filled(self, attempt_id: UUID, exchange_order_id: str) -> None:
        self.filled.append((attempt_id, exchange_order_id))

    async def mark_failed(self, attempt_id: UUID, error: str) -> None:
        self.failed.append((attempt_id, error))


@dataclass
class FakeFillRecorder:
    recorded: list[FillRecord] = field(default_factory=list)

    async def record(self, fill: FillRecord) -> None:
        self.recorded.append(fill)


@dataclass
class FakeUsdRateProvider:
    rate: Decimal = Decimal("1")

    async def usd_rate(self, currency: object) -> Decimal:
        return self.rate


@dataclass
class FakeCommit:
    committed: int = 0

    async def commit(self) -> None:
        self.committed += 1


def _reservation(**overrides: object) -> ReservationSnapshot:
    defaults: dict[str, object] = dict(
        id=uuid4(),
        strategy_id=uuid4(),
        venue="usdt-m",
        settlement_currency="USDT",
        amount=Decimal("200"),
        status="PENDING",
        expires_at=datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC),
    )
    defaults.update(overrides)
    return ReservationSnapshot(**defaults)  # type: ignore[arg-type]


def _build(
    *,
    reservation: ReservationSnapshot,
    now: datetime,
    exchange: FakeExchange | None = None,
) -> tuple[ExecuteReservation, FakeReservationGateway, FakeAttemptRepository, FakeExchange]:
    gateway = FakeReservationGateway(reservation=reservation)
    attempts = FakeAttemptRepository()
    exchange = exchange or FakeExchange(
        fill_to_return=Fill(
            exchange_order_id="ex-order-1",
            exchange_fill_id="ex-fill-1",
            quantity=Decimal("0.004"),
            price=Decimal("50010"),
            fee=Decimal("0.01"),
            fee_currency="USDT",
            filled_at=now,
        )
    )
    use_case = ExecuteReservation(
        reservations=gateway,
        exchange=exchange,
        attempts=attempts,
        fill_recorder=FakeFillRecorder(),
        usd_rate_provider=FakeUsdRateProvider(),
        clock=FrozenClock(now),
        commit=FakeCommit(),
    )
    return use_case, gateway, attempts, exchange


async def test_valid_reservation_submits_to_the_exchange() -> None:
    now = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    reservation = _reservation(expires_at=now + timedelta(seconds=20))
    use_case, gateway, attempts, exchange = _build(reservation=reservation, now=now)

    result = await use_case.execute(
        ExecuteCommand(
            reservation_id=reservation.id,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
        )
    )

    assert result.status == "FILLED"
    assert len(exchange.submitted) == 1
    assert len(attempts.inserted) == 1
    assert "RELEASED" not in [m[1] for m in gateway.marked]


async def test_expired_reservation_aborts_without_submitting() -> None:
    now = datetime(2026, 1, 1, 0, 0, 40, tzinfo=UTC)
    reservation = _reservation(expires_at=now - timedelta(seconds=1))
    use_case, gateway, attempts, exchange = _build(reservation=reservation, now=now)

    result = await use_case.execute(
        ExecuteCommand(
            reservation_id=reservation.id,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
        )
    )

    assert result.status == "ABORTED_EXPIRED"
    assert exchange.submitted == []
    assert attempts.inserted == []
    assert gateway.marked == [(reservation.id, "RELEASED", now)]


async def test_exchange_error_releases_the_reservation_and_marks_the_attempt_failed() -> None:
    now = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    reservation = _reservation(expires_at=now + timedelta(seconds=20))
    exchange = FakeExchange(error_to_raise=ExchangeError("exchange unreachable"))
    use_case, gateway, attempts, exchange = _build(
        reservation=reservation, now=now, exchange=exchange
    )

    result = await use_case.execute(
        ExecuteCommand(
            reservation_id=reservation.id,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
        )
    )

    assert result.status == "FAILED"
    assert attempts.failed == [(attempts.inserted[0].id, "exchange unreachable")]
    assert (reservation.id, "RELEASED", now) in gateway.marked


async def test_successful_fill_is_recorded_carrying_the_allocation_and_strategy_ids() -> None:
    now = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    strategy_id = uuid4()
    reservation = _reservation(expires_at=now + timedelta(seconds=20), strategy_id=strategy_id)
    gateway = FakeReservationGateway(reservation=reservation)
    attempts = FakeAttemptRepository()
    fill_recorder = FakeFillRecorder()
    exchange = FakeExchange(
        fill_to_return=Fill(
            exchange_order_id="ex-order-1",
            exchange_fill_id="ex-fill-1",
            quantity=Decimal("0.004"),
            price=Decimal("50010"),
            fee=Decimal("0.01"),
            fee_currency="USDT",
            filled_at=now,
        )
    )
    use_case = ExecuteReservation(
        reservations=gateway,
        exchange=exchange,
        attempts=attempts,
        fill_recorder=fill_recorder,
        usd_rate_provider=FakeUsdRateProvider(rate=Decimal("1.0001")),
        clock=FrozenClock(now),
        commit=FakeCommit(),
    )

    result = await use_case.execute(
        ExecuteCommand(
            reservation_id=reservation.id,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
        )
    )

    assert result.status == "FILLED"
    assert len(fill_recorder.recorded) == 1
    recorded = fill_recorder.recorded[0]
    assert recorded.allocation_id == reservation.id
    assert recorded.strategy_id == strategy_id
    assert recorded.venue == reservation.venue
    assert recorded.settlement_currency == reservation.settlement_currency
    assert recorded.usd_rate_at_fill == Decimal("1.0001")
    assert gateway.marked[-1] == (reservation.id, "FILLED", now)


async def test_order_quantity_is_granted_divided_by_price_never_from_alert_contracts() -> None:
    now = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    reservation = _reservation(amount=Decimal("200"), expires_at=now + timedelta(seconds=20))
    use_case, _, _, exchange = _build(reservation=reservation, now=now)

    await use_case.execute(
        ExecuteCommand(
            reservation_id=reservation.id,
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
        )
    )

    order = exchange.submitted[0]
    assert order.quantity == Decimal("0.004")  # 200 / 50000, never derived from `contracts`

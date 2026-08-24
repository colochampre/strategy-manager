"""``PlaceOrder`` — TXN-B1 and the unlocked network call.

The ordering test below is the one that matters. Settlement is scheduled
before the exchange is contacted, and if that ever inverts, an order can be
accepted with real money behind it while nothing in the system is scheduled
to find out.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.place_order import PlaceCommand, PlaceOrder
from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    PlacedOrder,
    ReservationSnapshot,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import (
    MarketBuy,
    MarketSell,
    OrderSide,
    market_order,
)
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
SETTLE_DELAY = 2.0
RESERVATION_ID = uuid4()
STRATEGY_ID = uuid4()


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeReservations:
    def __init__(self, expires_at: datetime, amount: Decimal = Decimal("100")) -> None:
        self._snapshot = ReservationSnapshot(
            id=RESERVATION_ID,
            strategy_id=STRATEGY_ID,
            venue="spot",
            settlement_currency="USDT",
            amount=amount,
            status="PENDING",
            expires_at=expires_at,
        )
        self.marks: list[tuple[UUID, str]] = []

    async def get_for_update(self, reservation_id: UUID) -> ReservationSnapshot:
        return self._snapshot

    async def mark(self, reservation_id: UUID, status: str, at: datetime) -> None:
        self.marks.append((reservation_id, status))


class SpyAttempts:
    def __init__(self, log: list[str]) -> None:
        self.inserted: list[ExecutionAttempt] = []
        self.placed: list[tuple[UUID, str]] = []
        self.failed: list[tuple[UUID, str]] = []
        self._log = log

    async def insert(self, attempt: ExecutionAttempt) -> None:
        self.inserted.append(attempt)
        self._log.append("attempt.insert")

    async def get(self, attempt_id: UUID) -> ExecutionAttempt:  # pragma: no cover
        raise NotImplementedError

    async def mark_placed(self, attempt_id: UUID, exchange_order_id: str) -> None:
        self.placed.append((attempt_id, exchange_order_id))

    async def mark_filled(self, attempt_id: UUID, exchange_order_id: str) -> None:
        raise NotImplementedError  # pragma: no cover

    async def mark_failed(self, attempt_id: UUID, error: str) -> None:
        self.failed.append((attempt_id, error))


class SpyQueue:
    def __init__(self, log: list[str]) -> None:
        self.enqueued: list[Job] = []
        self._log = log

    async def enqueue(self, job: Job) -> UUID:
        self.enqueued.append(job)
        self._log.append("queue.enqueue")
        return uuid4()


class SpyExchange:
    is_live = False
    venues = frozenset({"spot"})

    def __init__(self, log: list[str], raises: Exception | None = None) -> None:
        self.orders: list[PlaceableOrder] = []
        self.built: list[OpenOrderSpec] = []
        self._log = log
        self._raises = raises

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        """Real adapters build the order because denomination is a venue
        property. This double keeps spot's rule so the existing expectations
        still describe what a spot venue does."""
        self.built.append(spec)
        return market_order(
            side=spec.side,
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            granted=spec.granted,
            price=spec.price,
        )

    async def build_close_order(self, spec: CloseOrderSpec) -> PlaceableOrder:
        if spec.side is not OrderSide.SELL:
            raise ExchangeError(
                "closing a short is not supported on spot: a market buy "
                "cannot be sized in the base currency"
            )
        return MarketSell(
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            base_size=spec.base_size,
        )

    async def place(self, order: PlaceableOrder) -> PlacedOrder:
        self._log.append("exchange.place")
        if self._raises is not None:
            raise self._raises
        self.orders.append(order)
        return PlacedOrder(
            exchange_order_id="EX-1", client_order_id=order.client_order_id
        )

    async def fetch_fills(  # pragma: no cover - not used by PlaceOrder
        self, client_order_id: str, symbol: str
    ) -> list[Fill]:
        raise NotImplementedError


class SpyCommit:
    def __init__(self, log: list[str]) -> None:
        self.commits = 0
        self._log = log

    async def commit(self) -> None:
        self.commits += 1
        self._log.append("commit")


def _build(
    *,
    expires_at: datetime = NOW + timedelta(seconds=30),
    amount: Decimal = Decimal("100"),
    exchange_raises: Exception | None = None,
) -> tuple[PlaceOrder, FakeReservations, SpyAttempts, SpyQueue, SpyExchange, list[str]]:
    log: list[str] = []
    reservations = FakeReservations(expires_at, amount)
    attempts = SpyAttempts(log)
    queue = SpyQueue(log)
    exchange = SpyExchange(log, exchange_raises)
    use_case = PlaceOrder(
        reservations=reservations,
        exchanges=VenueExchangeRegistry([exchange]),  # type: ignore[list-item]
        attempts=attempts,  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        clock=FrozenClock(),
        commit=SpyCommit(log),
        settle_delay_seconds=SETTLE_DELAY,
    )
    return use_case, reservations, attempts, queue, exchange, log


def _command(
    price: Decimal = Decimal("50"), side: OrderSide = OrderSide.BUY
) -> PlaceCommand:
    return PlaceCommand(
        reservation_id=RESERVATION_ID,
        symbol="BTC_USDT",
        side=side,
        price=price,
    )


async def test_settlement_is_scheduled_before_the_exchange_is_contacted() -> None:
    """The whole crash-safety argument in one assertion. If the enqueue ever
    moves after the placement, an accepted order can exist with nothing
    scheduled to ever reconcile it."""
    use_case, _, _, _, _, log = _build()

    await use_case.place(_command())

    assert log.index("queue.enqueue") < log.index("exchange.place")
    assert log.index("commit") < log.index("exchange.place")


async def test_the_settle_job_names_the_attempt_and_runs_after_the_delay() -> None:
    use_case, _, attempts, queue, _, _ = _build()

    result = await use_case.place(_command())

    job = queue.enqueued[0]
    assert job.kind is JobKind.EXECUTION_SETTLE
    assert job.payload == {"execution_attempt_id": str(result.execution_attempt_id)}
    assert job.run_after == NOW + timedelta(seconds=SETTLE_DELAY)
    assert attempts.inserted[0].id == result.execution_attempt_id


async def test_a_placed_order_records_the_exchange_id() -> None:
    use_case, reservations, attempts, _, _, _ = _build()

    result = await use_case.place(_command())

    assert result.status == "PLACED"
    assert result.exchange_order_id == "EX-1"
    assert attempts.placed == [(result.execution_attempt_id, "EX-1")]
    assert (RESERVATION_ID, "SUBMITTED") in reservations.marks


async def test_a_buy_sends_the_granted_amount_untouched() -> None:
    """A market buy is denominated in the quote currency, which IS the
    settlement currency the reservation granted. So the granted amount goes on
    the wire verbatim — no division, and no dependency on a bar-close price
    that was already stale when the alert fired."""
    use_case, _, _, _, exchange, _ = _build(amount=Decimal("100"))

    await use_case.place(_command(price=Decimal("50")))

    order = exchange.orders[0]
    assert isinstance(order, MarketBuy)
    assert order.quote_amount == Decimal("100")


async def test_a_sell_size_comes_from_granted_over_price() -> None:
    """Never from the alert's contracts field (design.md's "Order size never
    comes from the alert")."""
    use_case, _, _, _, exchange, _ = _build(amount=Decimal("100"))

    await use_case.place(_command(price=Decimal("50"), side=OrderSide.SELL))

    order = exchange.orders[0]
    assert isinstance(order, MarketSell)
    assert order.base_size == Decimal("2")


async def test_the_attempt_records_the_size_that_actually_went_on_the_wire() -> None:
    """Exactly one of the two columns is ever populated. Storing a derived
    base quantity for a buy would put a number in the database that was never
    sent to anyone and can never be reconciled against the exchange."""
    use_case, _, attempts, _, _, _ = _build(amount=Decimal("100"))

    await use_case.place(_command(price=Decimal("50")))

    attempt = attempts.inserted[0]
    assert attempt.quantity is None
    assert attempt.quote_amount == Decimal("100")


async def test_an_expired_reservation_places_nothing() -> None:
    use_case, reservations, attempts, queue, exchange, _ = _build(
        expires_at=NOW - timedelta(seconds=1)
    )

    result = await use_case.place(_command())

    assert result.status == "ABORTED_EXPIRED"
    assert reservations.marks == [(RESERVATION_ID, "RELEASED")]
    assert exchange.orders == []
    assert queue.enqueued == []
    assert attempts.inserted == []


async def test_a_rejected_order_releases_the_reservation_immediately() -> None:
    """A rejection is definitive: the exchange saw it and refused. No reason
    to leave capital reserved until settlement reaches the same conclusion."""
    use_case, reservations, attempts, _, _, _ = _build(
        exchange_raises=ExchangeError("insufficient balance")
    )

    result = await use_case.place(_command())

    assert result.status == "FAILED"
    assert result.error == "insufficient balance"
    assert (RESERVATION_ID, "RELEASED") in reservations.marks
    assert attempts.failed[0][1] == "insufficient balance"


async def test_a_rejected_order_still_leaves_the_settle_job_scheduled() -> None:
    """It was enqueued before the call and is not withdrawn. Settlement is
    idempotent about an already-resolved attempt, which is cheaper than
    trying to unschedule work."""
    use_case, _, _, queue, _, _ = _build(
        exchange_raises=ExchangeError("insufficient balance")
    )

    await use_case.place(_command())

    assert len(queue.enqueued) == 1


async def test_a_zero_price_is_rejected_before_anything_is_written() -> None:
    """The quantity derivation runs before any write, so an unusable price
    cannot leave a half-built attempt or an orphan settle job behind."""
    use_case, reservations, attempts, queue, _, _ = _build()

    with pytest.raises(InvariantViolation, match="price must be positive"):
        await use_case.place(_command(price=Decimal("0")))

    assert queue.enqueued == []
    assert attempts.inserted == []
    assert reservations.marks == []

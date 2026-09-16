"""``ClosePosition`` — unwinding a position that an allocation opened.

These tests exist because the path they cover did not work at all. Closing used
to run through ``PlaceOrder`` against the opening reservation and could not
succeed in any timing window: inside the reservation's TTL the opening attempt
already owned the UNIQUE ``execution_attempts.reservation_id`` row, and outside
it — every real holding period — the pre-submit expiry re-check aborted the
order and flipped a FILLED reservation to RELEASED.

Nothing caught it because the only close coverage stubbed ``PlaceOrder`` out.
So the assertions here are deliberately about behaviour the old shape could not
express: a size that comes from the ledger, and an attempt that belongs to a
position rather than to a reservation.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    ClosePosition,
    NothingRecordedYet,
)
from strategy_manager.execution.application.ports import (
    CloseOrderSpec,
    ExchangeError,
    OpenOrderSpec,
    PlacedOrder,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import (
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

NOW = datetime(2026, 8, 21, 14, 0, 0, tzinfo=UTC)
SETTLE_DELAY = 2.0
ALLOCATION_ID = uuid4()
STRATEGY_ID = uuid4()


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeHeld:
    """Stands in for the ledger's projection of what the opening allocation
    actually acquired."""

    def __init__(self, net_base: Decimal) -> None:
        self._net_base = net_base
        self.asked: list[tuple[UUID, str]] = []

    async def net_base(self, allocation_id: UUID, base_currency: str) -> Decimal:
        self.asked.append((allocation_id, base_currency))
        return self._net_base


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

    async def mark_filled(  # pragma: no cover - not used by ClosePosition
        self, attempt_id: UUID, exchange_order_id: str
    ) -> None:
        raise NotImplementedError

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
    exchange = "pionex"
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
        return PlacedOrder(exchange_order_id="EX-9", client_order_id=order.client_order_id)

    async def fetch_fills(  # pragma: no cover - not used by ClosePosition
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
    net_base: Decimal = Decimal("0.00199960"),
    exchange_raises: Exception | None = None,
) -> tuple[ClosePosition, SpyAttempts, SpyQueue, SpyExchange, FakeHeld, list[str]]:
    log: list[str] = []
    attempts = SpyAttempts(log)
    queue = SpyQueue(log)
    exchange = SpyExchange(log, exchange_raises)
    held = FakeHeld(net_base)
    use_case = ClosePosition(
        exchanges=VenueExchangeRegistry([exchange]),  # type: ignore[list-item]
        attempts=attempts,  # type: ignore[arg-type]
        held=held,  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        clock=FrozenClock(),
        commit=SpyCommit(log),
        settle_delay_seconds=SETTLE_DELAY,
    )
    return use_case, attempts, queue, exchange, held, log


def _command(side: OrderSide = OrderSide.SELL) -> CloseCommand:
    return CloseCommand(exchange="pionex", 
        allocation_id=ALLOCATION_ID,
        strategy_id=STRATEGY_ID,
        venue="spot",
        settlement_currency="USDT",
        symbol="BTC_USDT",
        side=side,
    )


async def test_the_close_size_comes_from_the_ledger_not_from_a_price() -> None:
    """The whole point. The reservation knows what was granted in USDT;
    dividing that by any price does not reproduce what was bought, because the
    fill price differed from the alert's, a market order can fill in pieces,
    and a base-currency fee means less arrived than was purchased."""
    use_case, _, _, exchange, held, _ = _build(net_base=Decimal("0.00199960"))

    result = await use_case.close(_command())

    order = exchange.orders[0]
    assert isinstance(order, MarketSell)
    assert order.base_size == Decimal("0.00199960")
    assert result.base_size == Decimal("0.00199960")
    assert held.asked == [(ALLOCATION_ID, "BTC")]


async def test_settlement_is_scheduled_before_the_exchange_is_contacted() -> None:
    """The same crash-safety ordering PlaceOrder uses, and for the same
    reason: an accepted order must never exist with nothing scheduled to
    reconcile it."""
    use_case, _, _, _, _, log = _build()

    await use_case.close(_command())

    assert log.index("queue.enqueue") < log.index("exchange.place")
    assert log.index("commit") < log.index("exchange.place")


async def test_the_attempt_belongs_to_the_position_not_to_a_reservation() -> None:
    """A close reserves nothing. Recording it against the opening reservation
    is what used to collide with the UNIQUE constraint that gives opens their
    idempotency."""
    use_case, attempts, _, _, _, _ = _build()

    await use_case.close(_command())

    attempt = attempts.inserted[0]
    assert attempt.reservation_id is None
    assert attempt.closes_allocation_id == ALLOCATION_ID
    assert attempt.is_closing is True
    assert attempt.allocation_id == ALLOCATION_ID
    assert attempt.side is OrderSide.SELL


async def test_the_settle_job_names_the_closing_attempt() -> None:
    use_case, attempts, queue, _, _, _ = _build()

    result = await use_case.close(_command())

    job = queue.enqueued[0]
    assert job.kind is JobKind.EXECUTION_SETTLE
    assert job.payload == {"execution_attempt_id": str(result.execution_attempt_id)}
    assert job.run_after == NOW + timedelta(seconds=SETTLE_DELAY)
    assert attempts.inserted[0].id == result.execution_attempt_id


async def test_a_position_with_nothing_recorded_yet_is_retried_never_declared_closed() -> None:
    """Placement and settlement are separate jobs, so a close signal can arrive
    before the opening fills land. Reporting success there would abandon an open
    position while claiming it was closed."""
    use_case, attempts, queue, exchange, _, _ = _build(net_base=Decimal("0"))

    with pytest.raises(NothingRecordedYet):
        await use_case.close(_command())

    assert exchange.orders == []
    assert attempts.inserted == []
    assert queue.enqueued == []


async def test_closing_a_short_is_refused_rather_than_approximated() -> None:
    """A close of a short is a BUY, and a spot market buy is denominated in the
    quote currency — there is no way to ask it for an exact base quantity.
    Approximating with a quote amount leaves a residual position either way.

    Refused by the ADAPTER now, not by the use case: futures sizes both
    directions in the base currency, so this is spot's limitation and not a
    rule of closing. Still a DomainError, still raised before any attempt row
    exists. The holding is NEGATIVE here because that is what a short is.
    """
    use_case, attempts, _, exchange, _, _ = _build(net_base=Decimal("-0.00199960"))

    with pytest.raises(ExchangeError, match="closing a short"):
        await use_case.close(_command(side=OrderSide.BUY))

    assert exchange.orders == []
    assert attempts.inserted == []


async def test_a_short_is_a_negative_holding_not_an_empty_one() -> None:
    """The bug this guards: ``ReadHeldBase`` used to clamp at zero, so a short
    read as "nothing held", ``NothingRecordedYet`` fired, and the close
    retried forever with a real position open at the venue.

    Getting as far as the adapter's refusal is the assertion — it proves the
    close was SIZED, not discarded as empty."""
    use_case, _, _, _, _, _ = _build(net_base=Decimal("-0.0078"))

    with pytest.raises(ExchangeError):
        await use_case.close(_command(side=OrderSide.BUY))


async def test_a_holding_pointing_the_other_way_is_refused_before_any_order() -> None:
    """A close that SELLS unwinds a long, so the ledger must show a positive
    holding. If they disagree, one of them is wrong about a real position, and
    closing in the wrong direction does not flatten anything -- it doubles the
    exposure."""
    use_case, attempts, queue, exchange, _, _ = _build(net_base=Decimal("-0.0078"))

    with pytest.raises(InvariantViolation, match="would add exposure"):
        await use_case.close(_command(side=OrderSide.SELL))

    assert exchange.orders == []
    assert attempts.inserted == []
    assert queue.enqueued == []


async def test_a_rejected_close_releases_no_reservation() -> None:
    """There is nothing to release. The capital left the pool when the position
    opened and is still sitting in the base currency; the position simply stays
    open, and the failed attempt records why."""
    use_case, attempts, _, _, _, _ = _build(
        exchange_raises=ExchangeError("market closed")
    )

    result = await use_case.close(_command())

    assert result.status == "FAILED"
    assert result.error == "market closed"
    assert attempts.failed[0][1] == "market closed"


async def test_a_placed_close_records_the_exchange_id() -> None:
    use_case, attempts, _, _, _, _ = _build()

    result = await use_case.close(_command())

    assert result.status == "PLACED"
    assert result.exchange_order_id == "EX-9"
    assert attempts.placed == [(result.execution_attempt_id, "EX-9")]


async def test_a_symbol_the_pool_cannot_fund_is_refused_before_any_write() -> None:
    """A strategy in a USDT pool signalling a BTC-quoted market is
    misconfigured in a way that would otherwise surface as an inexplicably
    wrong order size."""
    use_case, attempts, queue, exchange, _, _ = _build()
    command = CloseCommand(exchange="pionex", 
        allocation_id=ALLOCATION_ID,
        strategy_id=STRATEGY_ID,
        venue="spot",
        settlement_currency="USDT",
        symbol="ETH_BTC",
        side=OrderSide.SELL,
    )

    with pytest.raises(InvariantViolation, match="cannot fund"):
        await use_case.close(command)

    assert exchange.orders == []
    assert attempts.inserted == []
    assert queue.enqueued == []

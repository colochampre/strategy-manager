"""``SettleExecution`` — TXN-B2, asking the exchange what an order became.

Three answers, three outcomes, and the distinction between the last two is
where money is lost or kept: an order the exchange never saw must release its
reservation, while an order whose fills have not been published yet must not.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.ports import (
    FillRecord,
    OrderNotFound,
    ReservationSnapshot,
)
from strategy_manager.execution.application.settle_execution import (
    NotSettledYet,
    SettleExecution,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionStatus,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderRequest, OrderSide
from strategy_manager.shared.domain.money import Currency

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
ATTEMPT_ID = uuid4()
RESERVATION_ID = uuid4()
STRATEGY_ID = uuid4()
CLIENT_ORDER_ID = "client-order-1"


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _closing_attempt(
    status: ExecutionStatus = ExecutionStatus.SUBMITTED,
) -> ExecutionAttempt:
    """A close: bound to the allocation it unwinds, not to a reservation, and
    denominated in the base currency it is selling."""
    return ExecutionAttempt(
        id=ATTEMPT_ID,
        reservation_id=None,
        closes_allocation_id=RESERVATION_ID,
        venue="spot",
        settlement_currency="USDT",
        symbol="BTC_USDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.00199960"),
        quote_amount=None,
        status=status,
        client_order_id=CLIENT_ORDER_ID,
    )


def _attempt(status: ExecutionStatus = ExecutionStatus.SUBMITTED) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=ATTEMPT_ID,
        reservation_id=RESERVATION_ID,
        closes_allocation_id=None,
        venue="spot",
        settlement_currency="USDT",
        symbol="BTC_USDT",
        side=OrderSide.BUY,
        # A buy carries its quote amount, never a base quantity: this attempt
        # spent 100 USDT and what that bought is whatever the fills say.
        quantity=None,
        quote_amount=Decimal("100"),
        status=status,
        client_order_id=CLIENT_ORDER_ID,
    )


def _fill(quantity: str, price: str, fill_id: str = "F-1") -> Fill:
    return Fill(
        exchange_order_id="EX-1",
        exchange_fill_id=fill_id,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal("0.1"),
        fee_currency="USDT",
        filled_at=NOW,
    )


class FakeReservations:
    def __init__(self) -> None:
        self.marks: list[tuple[UUID, str]] = []

    async def get_for_update(self, reservation_id: UUID) -> ReservationSnapshot:
        return ReservationSnapshot(
            id=RESERVATION_ID,
            strategy_id=STRATEGY_ID,
            venue="spot",
            settlement_currency="USDT",
            amount=Decimal("100"),
            status="SUBMITTED",
            expires_at=NOW,
        )

    async def mark(self, reservation_id: UUID, status: str, at: datetime) -> None:
        self.marks.append((reservation_id, status))


class FakeAttempts:
    def __init__(self, attempt: ExecutionAttempt) -> None:
        self._attempt = attempt
        self.filled: list[tuple[UUID, str]] = []
        self.failed: list[tuple[UUID, str]] = []

    async def insert(self, attempt: ExecutionAttempt) -> None:  # pragma: no cover
        raise NotImplementedError

    async def get(self, attempt_id: UUID) -> ExecutionAttempt:
        return self._attempt

    async def mark_placed(  # pragma: no cover
        self, attempt_id: UUID, exchange_order_id: str
    ) -> None:
        raise NotImplementedError

    async def mark_filled(self, attempt_id: UUID, exchange_order_id: str) -> None:
        self.filled.append((attempt_id, exchange_order_id))

    async def mark_failed(self, attempt_id: UUID, error: str) -> None:
        self.failed.append((attempt_id, error))


class FakeExchange:
    is_live = False

    def __init__(
        self, fills: list[Fill] | None = None, raises: Exception | None = None
    ) -> None:
        self._fills = fills or []
        self._raises = raises
        self.queried: list[str] = []

    async def place(self, order: OrderRequest) -> object:  # pragma: no cover
        raise NotImplementedError

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        self.queried.append(client_order_id)
        if self._raises is not None:
            raise self._raises
        return self._fills


class SpyLedger:
    def __init__(self) -> None:
        self.records: list[FillRecord] = []

    async def record(self, fill: FillRecord) -> None:
        self.records.append(fill)


class StubUsdRate:
    def __init__(self) -> None:
        self.calls = 0

    async def usd_rate(self, currency: Currency) -> Decimal:
        self.calls += 1
        return Decimal("1")


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _build(
    exchange: FakeExchange, attempt: ExecutionAttempt | None = None
) -> tuple[SettleExecution, FakeReservations, FakeAttempts, SpyLedger, StubUsdRate]:
    reservations = FakeReservations()
    attempts = FakeAttempts(attempt or _attempt())
    ledger = SpyLedger()
    usd_rate = StubUsdRate()
    use_case = SettleExecution(
        reservations=reservations,
        exchange=exchange,  # type: ignore[arg-type]
        attempts=attempts,  # type: ignore[arg-type]
        fill_recorder=ledger,  # type: ignore[arg-type]
        usd_rate_provider=usd_rate,
        clock=FrozenClock(),
        commit=SpyCommit(),
    )
    return use_case, reservations, attempts, ledger, usd_rate


async def test_the_order_is_looked_up_by_the_client_order_id() -> None:
    """Not the exchange's id: the client order id exists in the database
    before the order is placed, which is what makes a mid-flight crash
    recoverable."""
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, _, _ = _build(exchange)

    await use_case.settle(ATTEMPT_ID)

    assert exchange.queried == [CLIENT_ORDER_ID]


async def test_a_filled_order_reaches_the_ledger_and_goes_terminal() -> None:
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, reservations, attempts, ledger, _ = _build(exchange)

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "FILLED"
    assert len(ledger.records) == 1
    assert ledger.records[0].quantity == Decimal("2")
    assert ledger.records[0].price == Decimal("50")
    assert ledger.records[0].notional == Decimal("100")
    assert attempts.filled == [(ATTEMPT_ID, "EX-1")]
    assert reservations.marks == [(RESERVATION_ID, "FILLED")]


async def test_every_ledger_row_carries_its_strategy_and_allocation() -> None:
    """CLAUDE.md rule 6: every fill records strategy_id and allocation_id."""
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, ledger, _ = _build(exchange)

    await use_case.settle(ATTEMPT_ID)

    assert ledger.records[0].strategy_id == STRATEGY_ID
    assert ledger.records[0].allocation_id == RESERVATION_ID


async def test_a_market_order_filled_in_pieces_becomes_one_row_per_fill() -> None:
    """Averaging them would produce a ledger that cannot be reconciled
    against the exchange's own records."""
    exchange = FakeExchange(
        fills=[_fill("1", "50", "F-1"), _fill("1", "51", "F-2")]
    )
    use_case, _, _, ledger, _ = _build(exchange)

    result = await use_case.settle(ATTEMPT_ID)

    assert result.fills == 2
    assert [record.price for record in ledger.records] == [Decimal("50"), Decimal("51")]
    assert [record.exchange_fill_id for record in ledger.records] == ["F-1", "F-2"]


async def test_the_usd_rate_is_resolved_once_for_the_whole_settlement() -> None:
    """Rule 7 wants the rate at fill time, and all fills of one order settle
    at one instant — a per-row lookup would invent differences."""
    exchange = FakeExchange(fills=[_fill("1", "50", "F-1"), _fill("1", "51", "F-2")])
    use_case, _, _, _, usd_rate = _build(exchange)

    await use_case.settle(ATTEMPT_ID)

    assert usd_rate.calls == 1


async def test_an_order_the_exchange_never_saw_releases_the_reservation() -> None:
    """The worker died before placing. The capital was never spent, so it
    must go back to the pool rather than sit reserved forever."""
    exchange = FakeExchange(raises=OrderNotFound("no such client order id"))
    use_case, reservations, attempts, ledger, _ = _build(exchange)

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "NEVER_PLACED"
    assert reservations.marks == [(RESERVATION_ID, "RELEASED")]
    assert attempts.failed[0][0] == ATTEMPT_ID
    assert ledger.records == []


async def test_an_order_with_no_fills_yet_is_retried_not_released() -> None:
    """The dangerous confusion. 'Not published yet' and 'never happened' look
    identical from here, and releasing a reservation whose money is already
    committed would let the next signal spend it twice."""
    exchange = FakeExchange(fills=[])
    use_case, reservations, _, ledger, _ = _build(exchange)

    with pytest.raises(NotSettledYet):
        await use_case.settle(ATTEMPT_ID)

    assert reservations.marks == []
    assert ledger.records == []


async def test_an_already_resolved_attempt_is_left_alone() -> None:
    """Settlement is scheduled before placement, so it routinely arrives
    after a rejection already resolved the attempt. Re-recording would
    double-count fills in an append-only ledger."""
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, reservations, _, ledger, _ = _build(
        exchange, attempt=_attempt(ExecutionStatus.FAILED)
    )

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "ALREADY_SETTLED"
    assert exchange.queried == []
    assert ledger.records == []
    assert reservations.marks == []


async def test_a_second_settlement_of_a_filled_attempt_records_nothing() -> None:
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, ledger, _ = _build(
        exchange, attempt=_attempt(ExecutionStatus.FILLED)
    )

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "ALREADY_SETTLED"
    assert ledger.records == []


async def test_a_settled_close_writes_its_fills_under_the_opening_allocation() -> None:
    """Both sides of a position land in the same ``ledger_entries.allocation_id``
    column. That is what lets the close net against the open when positions are
    projected from the ledger, and what makes a second close read zero held."""
    exchange = FakeExchange([_fill("0.00199960", "50010")])
    use_case, _, _, ledger, _ = _build(exchange, attempt=_closing_attempt())

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "FILLED"
    assert ledger.records[0].allocation_id == RESERVATION_ID
    assert ledger.records[0].side == "SELL"
    assert ledger.records[0].strategy_id == STRATEGY_ID


async def test_a_settled_close_does_not_re_mark_the_reservation() -> None:
    """The reservation it is unwinding went FILLED when the position opened.
    Re-marking it would rewrite settled history to say what it already says —
    and a close has no reservation of its own to mark."""
    exchange = FakeExchange([_fill("0.00199960", "50010")])
    use_case, reservations, attempts, _, _ = _build(
        exchange, attempt=_closing_attempt()
    )

    await use_case.settle(ATTEMPT_ID)

    assert reservations.marks == []
    assert attempts.filled == [(ATTEMPT_ID, "EX-1")]


async def test_a_close_the_exchange_never_saw_releases_nothing() -> None:
    """The capital left the pool when the position opened and is still sitting
    in the base currency. Marking the opening reservation RELEASED here would
    claim money is available that is demonstrably still deployed — the position
    simply stays open, and the failed attempt records why."""
    exchange = FakeExchange(raises=OrderNotFound("no such order"))
    use_case, reservations, attempts, ledger, _ = _build(
        exchange, attempt=_closing_attempt()
    )

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "NEVER_PLACED"
    assert reservations.marks == []
    assert ledger.records == []
    assert attempts.failed[0][0] == ATTEMPT_ID

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
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)
from strategy_manager.shared.domain.money import Currency
from tests.execution.fakes import RecordingSettleOutcomes

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
ATTEMPT_ID = uuid4()
RESERVATION_ID = uuid4()
STRATEGY_ID = uuid4()
SIGNAL_ID = uuid4()
CLOSING_SIGNAL_ID = uuid4()
CLIENT_ORDER_ID = "client-order-1"


class FrozenClock:
    def now(self) -> datetime:
        return NOW


def _closing_attempt(
    status: ExecutionStatus = ExecutionStatus.SUBMITTED,
    signal_id: UUID | None = CLOSING_SIGNAL_ID,
) -> ExecutionAttempt:
    """A close: bound to the allocation it unwinds, not to a reservation, and
    denominated in the base currency it is selling."""
    return ExecutionAttempt(exchange="pionex", 
        id=ATTEMPT_ID,
        reservation_id=None,
        closes_allocation_id=RESERVATION_ID,
        venue="spot",
        settlement_currency="USDT",
        symbol="BTC_USDT",
        side=OrderSide.SELL,
        quantity=Decimal("0.00199960"),
        quote_amount=None,
        leverage=None,
        status=status,
        origin=ExecutionOrigin.SYSTEM,
        client_order_id=CLIENT_ORDER_ID,
        signal_id=signal_id,
    )


def _attempt(status: ExecutionStatus = ExecutionStatus.SUBMITTED) -> ExecutionAttempt:
    return ExecutionAttempt(exchange="pionex", 
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
        leverage=None,
        status=status,
        origin=ExecutionOrigin.SYSTEM,
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
        return ReservationSnapshot(exchange="pionex", 
            id=RESERVATION_ID,
            strategy_id=STRATEGY_ID,
            signal_id=SIGNAL_ID,
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
    exchange = "pionex"
    venues = frozenset({"spot"})

    def __init__(
        self, fills: list[Fill] | None = None, raises: Exception | None = None
    ) -> None:
        self._fills = fills or []
        self._raises = raises
        self.queried: list[str] = []

    async def place(self, order: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def build_open_order(self, spec: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def build_close_order(self, spec: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def fetch_fills(self, client_order_id: str, symbol: str) -> list[Fill]:
        self.queried.append(client_order_id)
        if self._raises is not None:
            raise self._raises
        return self._fills


class SpyLedger:
    def __init__(self, log: list[str] | None = None) -> None:
        self.records: list[FillRecord] = []
        self._log = log

    async def record(self, fill: FillRecord) -> None:
        self.records.append(fill)
        if self._log is not None:
            self._log.append("ledger.record")


class StubUsdRate:
    def __init__(self) -> None:
        self.calls = 0

    async def usd_rate(self, currency: Currency) -> Decimal:
        self.calls += 1
        return Decimal("1")


class SpyCommit:
    def __init__(self, log: list[str] | None = None) -> None:
        self.commits = 0
        self._log = log

    async def commit(self) -> None:
        self.commits += 1
        if self._log is not None:
            self._log.append("commit")


def _build(
    exchange: FakeExchange,
    attempt: ExecutionAttempt | None = None,
    outcomes: RecordingSettleOutcomes | None = None,
    log: list[str] | None = None,
) -> tuple[SettleExecution, FakeReservations, FakeAttempts, SpyLedger, StubUsdRate]:
    reservations = FakeReservations()
    attempts = FakeAttempts(attempt or _attempt())
    ledger = SpyLedger(log)
    usd_rate = StubUsdRate()
    outcomes = outcomes if outcomes is not None else RecordingSettleOutcomes()
    outcomes.log = log
    use_case = SettleExecution(
        reservations=reservations,
        exchanges=VenueExchangeRegistry([exchange]),  # type: ignore[list-item]
        attempts=attempts,  # type: ignore[arg-type]
        fill_recorder=ledger,  # type: ignore[arg-type]
        usd_rate_provider=usd_rate,
        clock=FrozenClock(),
        commit=SpyCommit(log),
        outcomes=outcomes,
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


# --------------------------------------------------------------------------
# 2f.4 -- a log line on FILLED and on NEVER_PLACED (orchestrator's outcome
# map, findings 16 and 17: this file imports no ``logging`` at all today,
# so the ONE place that learns an order's true fate leaves no trace).
# --------------------------------------------------------------------------


async def test_a_filled_order_logs_exactly_one_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger="strategy_manager.execution.application.settle_execution")
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, _, _ = _build(exchange)

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "FILLED"

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
    assert str(ATTEMPT_ID) in info_records[0].getMessage()


async def test_a_never_placed_order_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The only trace an order the exchange never saw leaves: whether its
    reservation was released depends on ``attempt.is_closing``, but the
    fact that nothing was ever placed does not."""
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.settle_execution")
    exchange = FakeExchange(raises=OrderNotFound("no such client order id"))
    use_case, _, _, _, _ = _build(exchange)

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "NEVER_PLACED"

    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 1
    assert str(ATTEMPT_ID) in warning_records[0].getMessage()


# --------------------------------------------------------------------------
# Decision 25, tasks 5c.1-5c.3 (design.md "Addendum: signal outcomes" § B
# rows 16-17): what settle tells the SIGNAL, staged on the very commit that
# makes the fills (or the release) durable.
# --------------------------------------------------------------------------


async def test_a_filled_open_ends_its_signal_processed_on_the_fills_commit() -> None:
    """5c.1. The signal is resolved through ``reservation.signal_id`` (the
    attempt here carries none, like every attempt written before 5c), and the
    write sits after the ledger rows and BEFORE the one commit."""
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(fills=[_fill("2", "50")]), outcomes=outcomes, log=log
    )

    await use_case.settle(ATTEMPT_ID)

    assert outcomes.open_filled == [SIGNAL_ID]
    assert outcomes.close_filled == []
    assert log == ["ledger.record", "outcome.open_filled", "commit"]


async def test_a_filled_close_resolves_the_closing_signal_never_the_opening_one() -> None:
    """5c.3. ``allocation_id`` of a close is the OPENING allocation, so its
    reservation names the OPENING signal (``SIGNAL_ID`` in this fake). The
    signal to tell is the one the attempt carries. Must fail if settle reads
    the reservation's signal for a close."""
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange([_fill("0.00199960", "50010")]),
        attempt=_closing_attempt(),
        outcomes=outcomes,
        log=log,
    )

    await use_case.settle(ATTEMPT_ID)

    assert outcomes.close_filled == [CLOSING_SIGNAL_ID]
    assert SIGNAL_ID not in outcomes.close_filled + outcomes.open_filled
    assert outcomes.open_filled == []
    assert log == ["ledger.record", "outcome.close_filled", "commit"]


async def test_a_filled_close_with_no_linked_signal_records_nothing() -> None:
    """An orphan close, or an attempt written before this PR: a NULL link
    records nothing, and the fills still land."""
    outcomes = RecordingSettleOutcomes()
    use_case, _, _, ledger, _ = _build(
        FakeExchange([_fill("0.00199960", "50010")]),
        attempt=_closing_attempt(signal_id=None),
        outcomes=outcomes,
    )

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "FILLED"
    assert len(ledger.records) == 1
    assert outcomes.nothing


async def test_a_never_placed_open_ends_its_signal_rejected_on_the_release_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """5c.2. Resolved through the reservation; the detail is the exact
    message logged, and the write sits before the release's one commit."""
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.settle_execution")
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(raises=OrderNotFound("no such client order id")),
        outcomes=outcomes,
        log=log,
    )

    await use_case.settle(ATTEMPT_ID)

    assert len(outcomes.never_placed) == 1
    [(signal_id, detail)] = outcomes.never_placed
    assert signal_id == SIGNAL_ID
    assert log == ["outcome.never_placed", "commit"]
    [warning] = [r for r in caplog.records if r.levelname == "WARNING"]
    assert detail == warning.getMessage()
    assert "reservation released" in detail


async def test_a_never_placed_close_ends_the_closing_signal_rejected() -> None:
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(raises=OrderNotFound("no such order")),
        attempt=_closing_attempt(),
        outcomes=outcomes,
        log=log,
    )

    await use_case.settle(ATTEMPT_ID)

    assert len(outcomes.never_placed) == 1
    [(signal_id, detail)] = outcomes.never_placed
    assert signal_id == CLOSING_SIGNAL_ID  # never the opening signal
    assert "position remains open" in detail
    assert log == ["outcome.never_placed", "commit"]


async def test_a_never_placed_close_with_no_linked_signal_records_nothing() -> None:
    outcomes = RecordingSettleOutcomes()
    use_case, _, attempts, _, _ = _build(
        FakeExchange(raises=OrderNotFound("no such order")),
        attempt=_closing_attempt(signal_id=None),
        outcomes=outcomes,
    )

    result = await use_case.settle(ATTEMPT_ID)

    assert result.status == "NEVER_PLACED"
    assert attempts.failed[0][0] == ATTEMPT_ID
    assert outcomes.nothing


async def test_settle_writes_no_outcome_when_it_has_not_decided_anything() -> None:
    """Not settled yet (retry) and already settled (redelivery): no fate was
    learned, so no outcome is written."""
    retry = RecordingSettleOutcomes()
    use_case, _, _, _, _ = _build(FakeExchange(fills=[]), outcomes=retry)
    with pytest.raises(NotSettledYet):
        await use_case.settle(ATTEMPT_ID)

    settled = RecordingSettleOutcomes()
    use_case, _, _, _, _ = _build(
        FakeExchange(fills=[_fill("2", "50")]),
        attempt=_attempt(ExecutionStatus.FILLED),
        outcomes=settled,
    )
    await use_case.settle(ATTEMPT_ID)

    assert retry.nothing and settled.nothing

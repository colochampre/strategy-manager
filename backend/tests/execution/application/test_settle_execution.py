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
# The delivery each attempt names (C.7): the row settle records its outcome on. The
# reservation of the closing attempt belongs to the OPENING delivery, never this one.
DELIVERY_ID = uuid4()
CLOSING_DELIVERY_ID = uuid4()
CLIENT_ORDER_ID = "client-order-1"
# The job's owner: the author of the strategy behind the attempt.
OWNER = UUID("0a1b2c3d-0000-4000-8000-0000000c0c0c")


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
        # The signal and the delivery travel together: an orphan close has neither.
        delivery_id=None if signal_id is None else CLOSING_DELIVERY_ID,
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
        delivery_id=DELIVERY_ID,
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
    """Records whose reservation each call was for (multi-user design AD8)."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.marks: list[tuple[UUID, str]] = []
        self.users: list[UUID] = []
        self._log = log

    async def get_for_update(self, user_id: UUID, reservation_id: UUID) -> ReservationSnapshot:
        self.users.append(user_id)
        if self._log is not None:
            self._log.append("reservation.get_for_update")
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

    async def mark(self, user_id: UUID, reservation_id: UUID, status: str, at: datetime) -> None:
        self.users.append(user_id)
        self.marks.append((reservation_id, status))


class FakeAttempts:
    def __init__(self, attempt: ExecutionAttempt) -> None:
        self._attempt = attempt
        self.filled: list[tuple[UUID, str]] = []
        self.failed: list[tuple[UUID, str]] = []
        # Whose attempt each call was for (multi-user design AD8).
        self.users: list[UUID] = []

    async def insert(self, user_id: UUID, attempt: ExecutionAttempt) -> None:  # pragma: no cover
        raise NotImplementedError

    async def get(self, user_id: UUID, attempt_id: UUID) -> ExecutionAttempt:
        self.users.append(user_id)
        return self._attempt

    async def mark_placed(  # pragma: no cover
        self, user_id: UUID, attempt_id: UUID, exchange_order_id: str
    ) -> None:
        raise NotImplementedError

    async def mark_filled(self, user_id: UUID, attempt_id: UUID, exchange_order_id: str) -> None:
        self.users.append(user_id)
        self.filled.append((attempt_id, exchange_order_id))

    async def mark_failed(self, user_id: UUID, attempt_id: UUID, error: str) -> None:
        self.users.append(user_id)
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


class FakePoolLock:
    """Records which pool each acquisition was for; ``log`` (optional) receives
    ``"pool_lock"`` in call order."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.acquired: list[tuple[UUID, str, str, str]] = []
        self._log = log

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self.acquired.append((user_id, exchange, venue, settlement_currency))
        if self._log is not None:
            self._log.append("pool_lock")


class FakeLeaving:
    """Stands in for the subscriptions side. ``log`` (optional) receives
    ``"leaving.end_if_flat"`` in call order."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.asked: list[tuple[UUID, UUID, str, str, str]] = []
        self._log = log

    async def end_if_flat(
        self,
        user_id: UUID,
        strategy_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
    ) -> bool:
        self.asked.append((user_id, strategy_id, exchange, venue, settlement_currency))
        if self._log is not None:
            self._log.append("leaving.end_if_flat")
        return False


def _build(
    exchange: FakeExchange,
    attempt: ExecutionAttempt | None = None,
    outcomes: RecordingSettleOutcomes | None = None,
    log: list[str] | None = None,
    trace_locks: bool = False,
    lock: FakePoolLock | None = None,
    leaving: FakeLeaving | None = None,
) -> tuple[SettleExecution, FakeReservations, FakeAttempts, SpyLedger, StubUsdRate]:
    reservations = FakeReservations(log if trace_locks else None)
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
        pool_lock=lock or FakePoolLock(log if trace_locks else None),
        leaving=leaving or FakeLeaving(log if trace_locks else None),
    )
    return use_case, reservations, attempts, ledger, usd_rate


async def test_the_order_is_looked_up_by_the_client_order_id() -> None:
    """Not the exchange's id: the client order id exists in the database
    before the order is placed, which is what makes a mid-flight crash
    recoverable."""
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, _, _ = _build(exchange)

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert exchange.queried == [CLIENT_ORDER_ID]


async def test_a_filled_order_reaches_the_ledger_and_goes_terminal() -> None:
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, reservations, attempts, ledger, _ = _build(exchange)

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.status == "FILLED"
    assert len(ledger.records) == 1
    assert ledger.records[0].quantity == Decimal("2")
    assert ledger.records[0].price == Decimal("50")
    assert ledger.records[0].notional == Decimal("100")
    assert attempts.filled == [(ATTEMPT_ID, "EX-1")]
    assert reservations.marks == [(RESERVATION_ID, "FILLED")]


async def test_the_reservation_read_and_marked_is_the_job_owners() -> None:
    """Multi-user design AD8 (B.5): settling reads and marks the reservation as
    the job owner's, on the FILLED path and on the never-placed release."""
    filled, filled_reservations, _, _, _ = _build(FakeExchange(fills=[_fill("2", "50")]))
    await filled.settle(OWNER, ATTEMPT_ID)

    released, released_reservations, _, _, _ = _build(FakeExchange(raises=OrderNotFound("x")))
    await released.settle(OWNER, ATTEMPT_ID)

    assert filled_reservations.users == [OWNER, OWNER]
    assert released_reservations.users == [OWNER, OWNER]


async def test_the_attempt_read_and_marked_is_the_job_owners() -> None:
    """Multi-user design AD8 (B.5): settling reads the attempt and marks it
    filled, or failed when the venue never saw it, as the job owner's."""
    filled, _, filled_attempts, _, _ = _build(FakeExchange(fills=[_fill("2", "50")]))
    await filled.settle(OWNER, ATTEMPT_ID)

    released, _, released_attempts, _, _ = _build(FakeExchange(raises=OrderNotFound("x")))
    await released.settle(OWNER, ATTEMPT_ID)

    assert filled_attempts.users == [OWNER, OWNER]  # get, mark_filled
    assert released_attempts.users == [OWNER, OWNER]  # get, mark_failed


async def test_every_ledger_row_carries_its_strategy_and_allocation() -> None:
    """CLAUDE.md rule 6: every fill records strategy_id and allocation_id."""
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, ledger, _ = _build(exchange)

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert ledger.records[0].strategy_id == STRATEGY_ID
    assert ledger.records[0].allocation_id == RESERVATION_ID


async def test_a_market_order_filled_in_pieces_becomes_one_row_per_fill() -> None:
    """Averaging them would produce a ledger that cannot be reconciled
    against the exchange's own records."""
    exchange = FakeExchange(
        fills=[_fill("1", "50", "F-1"), _fill("1", "51", "F-2")]
    )
    use_case, _, _, ledger, _ = _build(exchange)

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.fills == 2
    assert [record.price for record in ledger.records] == [Decimal("50"), Decimal("51")]
    assert [record.exchange_fill_id for record in ledger.records] == ["F-1", "F-2"]


async def test_the_usd_rate_is_resolved_once_for_the_whole_settlement() -> None:
    """Rule 7 wants the rate at fill time, and all fills of one order settle
    at one instant — a per-row lookup would invent differences."""
    exchange = FakeExchange(fills=[_fill("1", "50", "F-1"), _fill("1", "51", "F-2")])
    use_case, _, _, _, usd_rate = _build(exchange)

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert usd_rate.calls == 1


async def test_an_order_the_exchange_never_saw_releases_the_reservation() -> None:
    """The worker died before placing. The capital was never spent, so it
    must go back to the pool rather than sit reserved forever."""
    exchange = FakeExchange(raises=OrderNotFound("no such client order id"))
    use_case, reservations, attempts, ledger, _ = _build(exchange)

    result = await use_case.settle(OWNER, ATTEMPT_ID)

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
        await use_case.settle(OWNER, ATTEMPT_ID)

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

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.status == "ALREADY_SETTLED"
    assert exchange.queried == []
    assert ledger.records == []
    assert reservations.marks == []


async def test_a_second_settlement_of_a_filled_attempt_records_nothing() -> None:
    exchange = FakeExchange(fills=[_fill("2", "50")])
    use_case, _, _, ledger, _ = _build(
        exchange, attempt=_attempt(ExecutionStatus.FILLED)
    )

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.status == "ALREADY_SETTLED"
    assert ledger.records == []


async def test_a_settled_close_writes_its_fills_under_the_opening_allocation() -> None:
    """Both sides of a position land in the same ``ledger_entries.allocation_id``
    column. That is what lets the close net against the open when positions are
    projected from the ledger, and what makes a second close read zero held."""
    exchange = FakeExchange([_fill("0.00199960", "50010")])
    use_case, _, _, ledger, _ = _build(exchange, attempt=_closing_attempt())

    result = await use_case.settle(OWNER, ATTEMPT_ID)

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

    await use_case.settle(OWNER, ATTEMPT_ID)

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

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.status == "NEVER_PLACED"
    assert reservations.marks == []
    assert ledger.records == []
    assert attempts.failed[0][0] == ATTEMPT_ID


# --------------------------------------------------------------------------
# C.6 -- a close that books the last open allocation ends a LEAVING subscription
# --------------------------------------------------------------------------


async def test_a_settled_close_takes_the_pool_lock_first_and_then_asks_to_end_a_leaving_one() -> (
    None
):
    """Lock order: the user's pool lock BEFORE the reservation's row lock. The
    subscription is ended after the closing fill is recorded and before the one
    commit, so both land (or neither) together."""
    log: list[str] = []
    exchange = FakeExchange([_fill("0.00199960", "50010")])
    use_case, _, _, _, _ = _build(
        exchange, attempt=_closing_attempt(), log=log, trace_locks=True
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert log == [
        "pool_lock",
        "reservation.get_for_update",
        "ledger.record",
        "leaving.end_if_flat",
        "outcome.close_filled",
        "commit",
    ]


async def test_the_pool_locked_and_the_subscription_asked_about_are_the_job_owners() -> None:
    lock = FakePoolLock()
    leaving = FakeLeaving()
    use_case, _, _, _, _ = _build(
        FakeExchange([_fill("0.00199960", "50010")]),
        attempt=_closing_attempt(),
        lock=lock,
        leaving=leaving,
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert lock.acquired == [(OWNER, "pionex", "spot", "USDT")]
    assert leaving.asked == [(OWNER, STRATEGY_ID, "pionex", "spot", "USDT")]


async def test_a_settled_open_takes_no_pool_lock_and_ends_no_subscription() -> None:
    """An opening settlement is unchanged: it books fills for a reservation and
    needs neither the pool lock nor the subscription."""
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(fills=[_fill("2", "50")]), log=log, trace_locks=True
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert "pool_lock" not in log
    assert "leaving.end_if_flat" not in log


async def test_a_close_the_exchange_never_saw_ends_no_subscription() -> None:
    """The position stays open, so a LEAVING subscription stays LEAVING."""
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(raises=OrderNotFound("no such order")),
        attempt=_closing_attempt(),
        log=log,
        trace_locks=True,
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert "leaving.end_if_flat" not in log


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

    result = await use_case.settle(OWNER, ATTEMPT_ID)

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

    result = await use_case.settle(OWNER, ATTEMPT_ID)

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
    """5c.1. The delivery is the attempt's own link (C.7), and the write sits
    after the ledger rows and BEFORE the one commit."""
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(fills=[_fill("2", "50")]), outcomes=outcomes, log=log
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert outcomes.open_filled == [DELIVERY_ID]
    assert outcomes.close_filled == []
    assert log == ["ledger.record", "outcome.open_filled", "commit"]


async def test_a_filled_close_resolves_the_closing_signal_never_the_opening_one() -> None:
    """5c.3. ``allocation_id`` of a close is the OPENING allocation, so its
    reservation names the OPENING signal (``SIGNAL_ID`` in this fake). The
    delivery to tell is the one the attempt carries, and the signal handed beside
    it is the CLOSING one. Must fail if settle reads the reservation's for a
    close."""
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange([_fill("0.00199960", "50010")]),
        attempt=_closing_attempt(),
        outcomes=outcomes,
        log=log,
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert outcomes.close_filled == [CLOSING_DELIVERY_ID]
    assert outcomes.close_filled_signals == [CLOSING_SIGNAL_ID]
    assert DELIVERY_ID not in outcomes.close_filled + outcomes.open_filled
    assert SIGNAL_ID not in outcomes.close_filled_signals
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

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.status == "FILLED"
    assert len(ledger.records) == 1
    assert outcomes.nothing


async def test_a_never_placed_open_ends_its_signal_rejected_on_the_release_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """5c.2. Resolved through the attempt's delivery; the detail is the exact
    message logged, and the write sits before the release's one commit."""
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.settle_execution")
    outcomes = RecordingSettleOutcomes()
    log: list[str] = []
    use_case, _, _, _, _ = _build(
        FakeExchange(raises=OrderNotFound("no such client order id")),
        outcomes=outcomes,
        log=log,
    )

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert len(outcomes.never_placed) == 1
    [(delivery_id, detail)] = outcomes.never_placed
    assert delivery_id == DELIVERY_ID
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

    await use_case.settle(OWNER, ATTEMPT_ID)

    assert len(outcomes.never_placed) == 1
    [(delivery_id, detail)] = outcomes.never_placed
    assert delivery_id == CLOSING_DELIVERY_ID  # never the opening delivery
    assert "position remains open" in detail
    assert log == ["outcome.never_placed", "commit"]


async def test_a_never_placed_close_with_no_linked_signal_records_nothing() -> None:
    outcomes = RecordingSettleOutcomes()
    use_case, _, attempts, _, _ = _build(
        FakeExchange(raises=OrderNotFound("no such order")),
        attempt=_closing_attempt(signal_id=None),
        outcomes=outcomes,
    )

    result = await use_case.settle(OWNER, ATTEMPT_ID)

    assert result.status == "NEVER_PLACED"
    assert attempts.failed[0][0] == ATTEMPT_ID
    assert outcomes.nothing


async def test_settle_writes_no_outcome_when_it_has_not_decided_anything() -> None:
    """Not settled yet (retry) and already settled (redelivery): no fate was
    learned, so no outcome is written."""
    retry = RecordingSettleOutcomes()
    use_case, _, _, _, _ = _build(FakeExchange(fills=[]), outcomes=retry)
    with pytest.raises(NotSettledYet):
        await use_case.settle(OWNER, ATTEMPT_ID)

    settled = RecordingSettleOutcomes()
    use_case, _, _, _, _ = _build(
        FakeExchange(fills=[_fill("2", "50")]),
        attempt=_attempt(ExecutionStatus.FILLED),
        outcomes=settled,
    )
    await use_case.settle(OWNER, ATTEMPT_ID)

    assert retry.nothing and settled.nothing

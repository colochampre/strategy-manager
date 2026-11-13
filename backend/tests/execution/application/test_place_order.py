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
    LeverageConflict,
    LeverageNotApplied,
    MarginNotIsolated,
    OpenOrderSpec,
    OrderNotPlaceable,
    PlacedOrder,
    ReservationSnapshot,
)
from strategy_manager.execution.domain.execution_attempt import ExecutionAttempt
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.futures_order import FuturesMarketOrder
from strategy_manager.execution.domain.order import (
    MarketBuy,
    MarketSell,
    OrderSide,
    market_order,
)
from strategy_manager.execution.domain.placeable import PlaceableOrder
from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.domain.leverage import NEW_SEAT_LEVERAGE, Leverage
from strategy_manager.shared.domain.mode import Mode
from tests.execution.fakes import OneRegistry, RecordingOrderOutcomes

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
SETTLE_DELAY = 2.0
RESERVATION_ID = uuid4()
STRATEGY_ID = uuid4()
SIGNAL_ID = uuid4()
# The delivery whose work reserved it: every outcome of the order lands on this id.
DELIVERY_ID = uuid4()
# The reservation's owner: the author of the strategy whose signal allocated it.
OWNER = UUID("0a1b2c3d-0000-4000-8000-0000000d0d0d")


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeReservations:
    def __init__(
        self, expires_at: datetime, amount: Decimal = Decimal("100"), mode: Mode = Mode.LIVE
    ) -> None:
        self._snapshot = ReservationSnapshot(exchange="pionex",
            id=RESERVATION_ID,
            strategy_id=STRATEGY_ID,
            signal_id=SIGNAL_ID,
            venue="spot",
            settlement_currency="USDT",
            amount=amount,
            status="PENDING",
            mode=mode,
            expires_at=expires_at,
        )
        self.marks: list[tuple[UUID, str]] = []
        # Whose reservation each call was for (multi-user design AD8).
        self.users: list[UUID] = []

    async def get_for_update(self, user_id: UUID, reservation_id: UUID) -> ReservationSnapshot:
        self.users.append(user_id)
        return self._snapshot

    async def mark(self, user_id: UUID, reservation_id: UUID, status: str, at: datetime) -> None:
        self.users.append(user_id)
        self.marks.append((reservation_id, status))


class SpyAttempts:
    def __init__(self, log: list[str]) -> None:
        self.inserted: list[ExecutionAttempt] = []
        self.placed: list[tuple[UUID, str]] = []
        self.failed: list[tuple[UUID, str]] = []
        self._log = log
        # Whose attempt each call was for (multi-user design AD8).
        self.users: list[UUID] = []

    async def insert(self, user_id: UUID, attempt: ExecutionAttempt) -> None:
        self.users.append(user_id)
        self.inserted.append(attempt)
        self._log.append("attempt.insert")

    async def get(self, user_id: UUID, attempt_id: UUID) -> ExecutionAttempt:  # pragma: no cover
        raise NotImplementedError

    async def mark_placed(self, user_id: UUID, attempt_id: UUID, exchange_order_id: str) -> None:
        self.users.append(user_id)
        self.placed.append((attempt_id, exchange_order_id))

    async def mark_filled(
        self, user_id: UUID, attempt_id: UUID, exchange_order_id: str
    ) -> None:
        raise NotImplementedError  # pragma: no cover

    async def mark_failed(self, user_id: UUID, attempt_id: UUID, error: str) -> None:
        self.users.append(user_id)
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
    places_stop_after_fill = False

    def __init__(
        self,
        log: list[str],
        raises: Exception | None = None,
        build_open_raises: Exception | None = None,
    ) -> None:
        self.orders: list[PlaceableOrder] = []
        self.built: list[OpenOrderSpec] = []
        self._log = log
        self._raises = raises
        self._build_open_raises = build_open_raises

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        """Real adapters build the order because denomination is a venue
        property. This double keeps spot's rule so the existing expectations
        still describe what a spot venue does."""
        self.built.append(spec)
        if self._build_open_raises is not None:
            raise self._build_open_raises
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


class SpyStops:
    """``ProtectiveStopRepositoryPort``: what was written, as whom, in call order."""

    def __init__(self, log: list[str]) -> None:
        self.inserted: list[ProtectiveStop] = []
        self.marked: list[tuple[UUID, StopStatus]] = []
        self.users: list[UUID] = []
        self._log = log

    async def insert(self, user_id: UUID, stop: ProtectiveStop) -> None:
        self.users.append(user_id)
        self.inserted.append(stop)
        self._log.append("stop.insert")

    async def for_attempt(  # pragma: no cover - not used by PlaceOrder
        self, user_id: UUID, attempt_id: UUID
    ) -> ProtectiveStop | None:
        raise NotImplementedError

    async def mark(
        self,
        user_id: UUID,
        attempt_id: UUID,
        status: StopStatus,
        venue_stop_id: str | None = None,
    ) -> None:
        self.users.append(user_id)
        self.marked.append((attempt_id, status))
        self._log.append(f"stop.mark {status.value}")


class FuturesSpyExchange(SpyExchange):
    """An adapter that builds a futures opening: with a stop on the order (a live Bybit),
    or with none (a live Binance until SS.6, or a simulated exchange)."""

    venues = frozenset({"spot"})

    def __init__(
        self,
        log: list[str],
        *,
        stop_price: Decimal | None,
        live: bool,
        raises: Exception | None = None,
    ) -> None:
        super().__init__(log, raises)
        self.is_live = live
        self._stop_price = stop_price

    async def build_open_order(self, spec: OpenOrderSpec) -> PlaceableOrder:
        self.built.append(spec)
        return FuturesMarketOrder(
            client_order_id=spec.client_order_id,
            symbol=spec.symbol,
            side=spec.side,
            base_size=Decimal("76"),
            leverage=Decimal("3"),
            stop_price=self._stop_price,
        )


def _build(
    *,
    expires_at: datetime = NOW + timedelta(seconds=30),
    amount: Decimal = Decimal("100"),
    exchange_raises: Exception | None = None,
    build_open_raises: Exception | None = None,
    outcomes: RecordingOrderOutcomes | None = None,
    mode: Mode = Mode.LIVE,
    asked: list[Mode] | None = None,
    stops: SpyStops | None = None,
    log: list[str] | None = None,
    futures: tuple[Decimal | None, bool] | None = None,
    after_fill: bool = False,
) -> tuple[PlaceOrder, FakeReservations, SpyAttempts, SpyQueue, SpyExchange, list[str]]:
    """``log`` lets a test share its own with a ``SpyStops``; ``futures`` is ``(the stop
    price the adapter puts on the order, whether the adapter is live)`` for a venue that
    builds a futures opening, and the default is the spot double every older test uses.
    ``after_fill`` is whether that adapter places its stop after the fill (Binance)."""
    log = log if log is not None else []
    outcomes = outcomes if outcomes is not None else RecordingOrderOutcomes()
    outcomes.log = log
    reservations = FakeReservations(expires_at, amount, mode)
    attempts = SpyAttempts(log)
    queue = SpyQueue(log)
    exchange: SpyExchange
    if futures is not None:
        exchange = FuturesSpyExchange(
            log, stop_price=futures[0], live=futures[1], raises=exchange_raises
        )
        exchange.places_stop_after_fill = after_fill
    else:
        exchange = SpyExchange(log, exchange_raises, build_open_raises)
    use_case = PlaceOrder(
        stops=stops if stops is not None else SpyStops(log),
        reservations=reservations,
        exchanges=OneRegistry(
            VenueExchangeRegistry([exchange]),  # type: ignore[list-item]
            [] if asked is None else asked,
        ),
        attempts=attempts,  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        clock=FrozenClock(),
        commit=SpyCommit(log),
        settle_delay_seconds=SETTLE_DELAY,
        outcomes=outcomes,
    )
    return use_case, reservations, attempts, queue, exchange, log


def _command(
    price: Decimal = Decimal("50"),
    side: OrderSide = OrderSide.BUY,
    leverage: Leverage = NEW_SEAT_LEVERAGE,
    stop_loss_pct: Decimal = Decimal("10"),
) -> PlaceCommand:
    return PlaceCommand(
        user_id=OWNER,
        delivery_id=DELIVERY_ID,
        reservation_id=RESERVATION_ID,
        symbol="BTC_USDT",
        side=side,
        price=price,
        stop_loss_pct=stop_loss_pct,
        leverage=leverage,
    )


async def test_the_order_is_built_at_the_commands_leverage() -> None:
    """The subscription's leverage reaches the adapter (decision 38, H.4); how it
    sizes by it is the adapter's business."""
    use_case, _, _, _, exchange, _ = _build()

    await use_case.place(_command(leverage=Leverage(7)))

    assert [spec.leverage for spec in exchange.built] == [Leverage(7)]


@pytest.mark.parametrize("mode", list(Mode))
async def test_the_order_goes_to_the_exchanges_of_the_reservations_mode(mode: Mode) -> None:
    """Multi-user design AD7, tasks.md E.4: the mode was decided in the lock and
    recorded. A flip or the brake landing after that changes nothing for this order,
    so ``PlaceOrder`` reads no mode of its own."""
    asked: list[Mode] = []
    use_case, _, _, _, exchange, _ = _build(mode=mode, asked=asked)

    await use_case.place(_command())

    assert asked == [mode]
    assert len(exchange.orders) == 1


async def test_an_expired_reservation_builds_no_exchange() -> None:
    """A job builds an adapter only when it needs one: a live one decrypts a key."""
    asked: list[Mode] = []
    use_case, _, _, _, _, _ = _build(expires_at=NOW - timedelta(seconds=1), asked=asked)

    await use_case.place(_command())

    assert asked == []


async def test_the_reservation_read_and_marked_is_the_commands_user() -> None:
    """Multi-user design AD8 (B.5): the reservation is read and marked as the
    command's user, the strategy author whose signal allocated it, on the
    placed path and on the expired release."""
    placed, placed_reservations, _, _, _, _ = _build()
    await placed.place(_command())

    expired, expired_reservations, _, _, _, _ = _build(expires_at=NOW - timedelta(seconds=1))
    await expired.place(_command())

    assert placed_reservations.users == [OWNER, OWNER]
    assert expired_reservations.users == [OWNER, OWNER]


async def test_the_attempt_is_written_and_marked_as_the_commands_user() -> None:
    """Multi-user design AD2/AD8 (B.5): the attempt is inserted as the user of
    the reservation it spends, and marked placed as the same user; a venue
    rejection marks it failed as that user too."""
    placed, _, placed_attempts, _, _, _ = _build()
    await placed.place(_command())

    rejected, _, rejected_attempts, _, _, _ = _build(
        exchange_raises=ExchangeError("insufficient balance")
    )
    await rejected.place(_command())

    assert placed_attempts.users == [OWNER, OWNER]  # insert, mark_placed
    assert rejected_attempts.users == [OWNER, OWNER]  # insert, mark_failed


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


async def test_an_order_not_placeable_ends_the_signal_without_raising() -> None:
    """The bug this task exists to fix: ``build_open_order`` raises before any
    write, outside the ``try/except ExchangeError`` that only ever wrapped
    ``exchange.place``. Before this fix, ``OrderNotPlaceable`` propagated
    straight out of ``place()`` into ``WorkerRunner``, which logged a WARNING
    and retried with backoff until the job died FAILED -- a size the venue's
    own catalogue will never accept, retried forever. It must never raise; it
    must be translated into a refused result instead."""
    reason = (
        "BTCUSDT rounds a size of 0.0002 down to 0.000 at a step of 0.001; "
        "the granted 20 is too small to open a position at 1x"
    )
    use_case, reservations, attempts, queue, _, _ = _build(
        build_open_raises=OrderNotPlaceable(
            reason,
            symbol="BTCUSDT",
            size=Decimal("0"),
            minimum=Decimal("0.001"),
            step=Decimal("0.001"),
        )
    )

    try:
        result = await use_case.place(_command())
    except OrderNotPlaceable:
        pytest.fail(
            "OrderNotPlaceable must not propagate out of PlaceOrder.place() -- "
            "it is a definitive refusal, not a retryable failure"
        )

    assert result.status == "REFUSED"
    assert result.execution_attempt_id is None
    assert result.error == reason


async def test_an_order_not_placeable_releases_the_reservation_and_writes_no_attempt() -> None:
    """Definitive, like a rejected order -- but unlike one, nothing was ever
    written: build happens before the attempt insert and the settle-job
    enqueue, so there is no attempt to mark failed and no orphan settle job
    to leave scheduled."""
    use_case, reservations, attempts, queue, _, _ = _build(
        build_open_raises=OrderNotPlaceable(
            "too small",
            symbol="BTCUSDT",
            size=Decimal("0"),
            minimum=Decimal("0.001"),
            step=Decimal("0.001"),
        )
    )

    await use_case.place(_command())

    assert reservations.marks == [(RESERVATION_ID, "RELEASED")]
    assert attempts.inserted == []
    assert queue.enqueued == []


async def test_an_order_not_placeable_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The only trace of a refused open, so it must be self-sufficient: which
    reservation was released, which strategy, which symbol, and why."""
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.place_order")
    reason = "BTCUSDT is too small to open a position"
    use_case, _, _, _, _, _ = _build(
        build_open_raises=OrderNotPlaceable(
            reason,
            symbol="BTCUSDT",
            size=Decimal("0"),
            minimum=Decimal("0.001"),
            step=Decimal("0.001"),
        )
    )

    await use_case.place(_command())

    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 1
    message = warning_records[0].getMessage()
    assert str(RESERVATION_ID) in message
    assert str(STRATEGY_ID) in message
    assert "BTC_USDT" in message


# --------------------------------------------------------------------------
# 2f.2 / 2f.3 -- a log line on ABORTED_EXPIRED and on a venue rejection at
# submit (orchestrator's outcome map, findings 9 and 11: both currently
# silent, and both discarded again by ``process_signal.py`` since it never
# even reads ``PlaceResult``).
# --------------------------------------------------------------------------


async def test_an_expired_reservation_logs_exactly_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The only trace an expired reservation ever leaves: no order was
    placed, and nothing else records why."""
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.place_order")
    use_case, reservations, _, _, _, _ = _build(expires_at=NOW - timedelta(seconds=1))

    result = await use_case.place(_command())

    assert result.status == "ABORTED_EXPIRED"
    assert reservations.marks == [(RESERVATION_ID, "RELEASED")]

    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_records) == 1
    assert str(RESERVATION_ID) in warning_records[0].getMessage()


async def test_a_rejected_order_logs_exactly_one_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ERROR, not WARNING: a definitive venue rejection reaches Telegram
    because an order that did not happen is exactly the kind of thing an
    owner needs paged for, not merely logged."""
    caplog.set_level("ERROR", logger="strategy_manager.execution.application.place_order")
    use_case, _, _, _, _, _ = _build(exchange_raises=ExchangeError("insufficient balance"))

    result = await use_case.place(_command())

    assert result.status == "FAILED"

    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert str(RESERVATION_ID) in message
    assert "BTC_USDT" in message
    assert "insufficient balance" in message


# --------------------------------------------------------------------------
# Decision 25, rows 9-12 (tasks 5b.6): each definitive end of an order is
# recorded on the signal, staged immediately before the commit that makes it
# durable. ``RecordingOrderOutcomes`` shares the use case's call log, so the
# ORDER of "outcome.*" against "commit" is what proves the same-commit rule.
# --------------------------------------------------------------------------


async def test_an_expired_reservation_rejects_the_signal_on_its_release_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.place_order")
    outcomes = RecordingOrderOutcomes()
    use_case, _, _, _, _, log = _build(expires_at=NOW - timedelta(seconds=1), outcomes=outcomes)

    await use_case.place(_command())

    logged = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert outcomes.rejected == [
        (DELIVERY_ID, "RESERVATION_EXPIRED_BEFORE_SUBMIT", logged[0])
    ]
    assert outcomes.processing == []
    # Staged first, then the ONE commit that also carries the release.
    assert log == ["outcome.rejected", "commit"]


async def test_an_order_not_placeable_rejects_the_signal_on_its_release_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.place_order")
    outcomes = RecordingOrderOutcomes()
    use_case, _, _, _, _, log = _build(
        build_open_raises=OrderNotPlaceable(
            "BTCUSDT is too small to open a position",
            symbol="BTCUSDT",
            size=Decimal("0"),
            minimum=Decimal("0.001"),
            step=Decimal("0.001"),
        ),
        outcomes=outcomes,
    )

    await use_case.place(_command())

    logged = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert outcomes.rejected == [(DELIVERY_ID, "ORDER_NOT_PLACEABLE", logged[0])]
    assert "BTCUSDT is too small to open a position" in logged[0]
    assert outcomes.processing == []
    assert log == ["outcome.rejected", "commit"]


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (LeverageNotApplied("BTCUSDT read back at 20x, not 2x"), "LEVERAGE_NOT_APPLIED"),
        (MarginNotIsolated("BTCUSDT read back as CROSSED"), "MARGIN_NOT_ISOLATED"),
        (LeverageConflict("BTCUSDT is held at 3x, this opening asks 2x"), "LEVERAGE_CONFLICT"),
    ],
    ids=["not-applied", "not-isolated", "conflict"],
)
async def test_a_refused_setting_releases_the_reservation_and_rejects_by_name_as_an_error(
    caplog: pytest.LogCaptureFixture, refusal: Exception, code: str
) -> None:
    """Decision 38 (H.5): the venue decided, so the opening ends here, as an
    unplaceable size does, but as an ERROR: it reaches Telegram, because a
    setting the user chose did not hold. Nothing was written to the attempts."""
    caplog.set_level("WARNING", logger="strategy_manager.execution.application.place_order")
    outcomes = RecordingOrderOutcomes()
    use_case, reservations, attempts, queue, exchange, log = _build(
        build_open_raises=refusal, outcomes=outcomes
    )

    result = await use_case.place(_command())

    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert result.status == "REFUSED"
    assert reservations.marks == [(RESERVATION_ID, "RELEASED")]
    assert outcomes.rejected == [(DELIVERY_ID, code, errors[0])]
    assert str(refusal) in errors[0]
    assert str(RESERVATION_ID) in errors[0]
    assert exchange.orders == []
    assert log == ["outcome.rejected", "commit"]


async def test_a_venue_rejection_rejects_the_signal_on_the_post_network_commit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Row 11 rides the commit AFTER the network call (release + mark_failed),
    never the pre-network SUBMITTED one: at that earlier commit nothing is
    known about the venue's answer yet."""
    caplog.set_level("ERROR", logger="strategy_manager.execution.application.place_order")
    outcomes = RecordingOrderOutcomes()
    use_case, _, _, _, _, log = _build(
        exchange_raises=ExchangeError("insufficient balance"), outcomes=outcomes
    )

    await use_case.place(_command())

    logged = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert outcomes.rejected == [(DELIVERY_ID, "ORDER_REJECTED_BY_VENUE", logged[0])]
    assert outcomes.processing == []
    assert log == [
        "attempt.insert",
        "queue.enqueue",
        "commit",
        "exchange.place",
        "outcome.rejected",
        "commit",
    ]


async def test_a_placed_order_leaves_the_signal_processing_on_the_placed_commit() -> None:
    """Row 12: PROCESSING, never PROCESSED and never REJECTED, staged on the
    ``mark_placed`` commit -- not the earlier SUBMITTED commit, which only
    says the attempt was written, not that the exchange accepted it."""
    outcomes = RecordingOrderOutcomes()
    use_case, _, _, _, _, log = _build(outcomes=outcomes)

    await use_case.place(_command())

    assert outcomes.processing == [DELIVERY_ID]
    assert outcomes.rejected == []
    assert log == [
        "attempt.insert",
        "queue.enqueue",
        "commit",
        "exchange.place",
        "outcome.processing",
        "commit",
    ]


async def test_the_opening_attempt_is_linked_to_the_signal_of_its_reservation() -> None:
    """Decision 25, 5c.3: the attempt insert carries ``signal_id`` so a later
    reader can resolve the attempt to the signal it was placed for."""
    use_case, _, attempts, _, _, _ = _build()

    await use_case.place(_command())

    assert attempts.inserted[0].signal_id == SIGNAL_ID


async def test_the_opening_attempt_is_linked_to_the_delivery_of_its_command() -> None:
    """C.7: settle records the order's outcome on the delivery the attempt names,
    beside the signal link (the strategy history still counts attempts through
    the signal)."""
    use_case, _, attempts, _, _, _ = _build()

    await use_case.place(_command())

    assert attempts.inserted[0].delivery_id == DELIVERY_ID
    assert attempts.inserted[0].signal_id == SIGNAL_ID


# ---- the protective stop's row (subscriber-safety SS.5) ----------------------------


async def test_a_live_opening_that_carries_a_stop_writes_a_pending_row_for_it() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, _, attempts, _, exchange, _ = _build(
        stops=stops, log=log, futures=(Decimal("72.00"), True)
    )

    await use_case.place(_command(side=OrderSide.BUY, stop_loss_pct=Decimal("7.5")))

    [stop] = stops.inserted
    [attempt] = attempts.inserted
    assert stop.status is StopStatus.PENDING
    assert stop.execution_attempt_id == attempt.id
    assert stop.allocation_id == RESERVATION_ID
    assert (stop.exchange, stop.venue) == ("pionex", "spot")
    assert stop.symbol == "BTC_USDT"
    assert stop.position_side is PositionSide.LONG
    assert stop.stop_loss_pct == Decimal("7.5")
    assert stop.trigger_price == Decimal("72.00")
    assert stop.venue_stop_id is None
    assert stops.users == [OWNER]
    # The adapter was asked to build at the very level the row records.
    assert [spec.stop_loss_pct for spec in exchange.built] == [Decimal("7.5")]


async def test_a_short_opening_records_a_short_position() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log, futures=(Decimal("88.00"), True))

    await use_case.place(_command(side=OrderSide.SELL))

    [stop] = stops.inserted
    assert stop.position_side is PositionSide.SHORT


async def test_the_stop_row_is_written_with_the_attempt_and_before_the_order_is_sent() -> None:
    """A crash after the order reaches the venue leaves a trace of a stop that may exist
    there: the row rides the same commit as the attempt and the settle job."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log, futures=(Decimal("72.00"), True))

    await use_case.place(_command())

    first_commit = log.index("commit")
    assert log.index("attempt.insert") < log.index("stop.insert") < first_commit
    assert log.index("queue.enqueue") < first_commit < log.index("exchange.place")


async def test_a_simulated_opening_records_the_level_and_no_trigger_price() -> None:
    """The simulated venue places no stop and does not fire one, but the level the
    opening would have used is recorded."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(
        stops=stops, log=log, mode=Mode.SIMULATION, futures=(None, False)
    )

    await use_case.place(_command(stop_loss_pct=Decimal("12.5")))

    [stop] = stops.inserted
    assert stop.status is StopStatus.SIMULATED
    assert stop.stop_loss_pct == Decimal("12.5")
    assert stop.trigger_price is None
    assert stop.venue_stop_id is None


async def test_a_live_opening_on_a_venue_that_attaches_no_stop_writes_no_row() -> None:
    """Binance, until SS.6: a PENDING row nobody would ever confirm would read as a
    protected position."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log, futures=(None, True))

    await use_case.place(_command())

    assert stops.inserted == []


async def test_a_live_opening_on_a_venue_that_places_its_stop_after_the_fill_writes_a_pending_row(
) -> None:
    """Binance (SS.6): the order carries no stop, but the row is written now, with the id
    the stop will be sent under and no trigger price, because that is worked out from the
    fills."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, _, attempts, *_ = _build(
        stops=stops, log=log, futures=(None, True), after_fill=True
    )

    await use_case.place(_command(side=OrderSide.BUY, stop_loss_pct=Decimal("7.5")))

    assert len(stops.inserted) == 1
    [stop] = stops.inserted
    [attempt] = attempts.inserted
    assert stop.status is StopStatus.PENDING
    assert stop.execution_attempt_id == attempt.id
    assert stop.allocation_id == RESERVATION_ID
    assert stop.symbol == "BTC_USDT"
    assert stop.position_side is PositionSide.LONG
    assert stop.stop_loss_pct == Decimal("7.5")
    assert stop.trigger_price is None
    assert stop.venue_stop_id is None
    # A UUID4, exactly the 36 characters Binance's ``clientAlgoId`` allows, and not the
    # opening's own id: the two orders are found by their own handles.
    assert stop.client_stop_id is not None
    assert len(stop.client_stop_id) == 36
    assert str(UUID(stop.client_stop_id)) == stop.client_stop_id
    assert stop.client_stop_id != attempt.client_order_id
    assert stops.users == [OWNER]


async def test_a_short_opening_on_that_venue_records_a_short_position() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log, futures=(None, True), after_fill=True)

    await use_case.place(_command(side=OrderSide.SELL))

    assert len(stops.inserted) == 1
    assert stops.inserted[0].position_side is PositionSide.SHORT


async def test_the_client_stop_id_is_recorded_before_the_order_is_sent() -> None:
    """The whole point of recording it: any request that might reach the venue for this
    stop comes after a commit that holds the id, so a crash can read it back."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log, futures=(None, True), after_fill=True)

    await use_case.place(_command())

    first_commit = log.index("commit")
    assert log.index("attempt.insert") < log.index("stop.insert") < first_commit
    assert log.index("queue.enqueue") < first_commit < log.index("exchange.place")


async def test_every_opening_gets_its_own_client_stop_id() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    first, *_ = _build(stops=stops, log=log, futures=(None, True), after_fill=True)
    second, *_ = _build(stops=stops, log=log, futures=(None, True), after_fill=True)

    await first.place(_command())
    await second.place(_command())

    ids = [stop.client_stop_id for stop in stops.inserted]
    assert len(ids) == 2 and ids[0] != ids[1]


async def test_a_simulated_opening_places_no_stop_even_on_an_adapter_flagged_for_one() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(
        stops=stops, log=log, mode=Mode.SIMULATION, futures=(None, False), after_fill=True
    )

    await use_case.place(_command())

    assert len(stops.inserted) == 1
    assert stops.inserted[0].status is StopStatus.SIMULATED
    assert stops.inserted[0].client_stop_id is None


async def test_a_stop_riding_the_order_has_no_client_stop_id() -> None:
    """Bybit: the stop is on the opening order and found by its parent, never by an id of
    its own."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log, futures=(Decimal("72.00"), True))

    await use_case.place(_command())

    assert len(stops.inserted) == 1
    assert stops.inserted[0].client_stop_id is None


async def test_a_refused_opening_voids_the_stop_placed_after_the_fill_too() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, _, attempts, *_ = _build(
        stops=stops,
        log=log,
        exchange_raises=ExchangeError("insufficient balance"),
        futures=(None, True),
        after_fill=True,
    )

    await use_case.place(_command())

    [attempt] = attempts.inserted
    assert stops.marked == [(attempt.id, StopStatus.VOID)]


async def test_a_spot_opening_writes_no_stop_row() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(stops=stops, log=log)

    await use_case.place(_command())

    assert stops.inserted == []
    assert stops.marked == []


async def test_a_definitive_refusal_voids_the_stop_on_the_same_commit_as_the_release() -> None:
    """The opening ended without fills, so no stop ever mattered."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, _, attempts, *_ = _build(
        stops=stops,
        log=log,
        exchange_raises=ExchangeError("insufficient balance"),
        futures=(Decimal("72.00"), True),
    )

    await use_case.place(_command())

    [attempt] = attempts.inserted
    assert stops.marked == [(attempt.id, StopStatus.VOID)]
    assert stops.users == [OWNER, OWNER]  # insert, mark
    refused_at = log.index("exchange.place")
    assert refused_at < log.index("stop.mark VOID") < len(log) - 1 - log[::-1].index("commit")


async def test_a_refused_opening_with_no_row_marks_nothing() -> None:
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(
        stops=stops,
        log=log,
        exchange_raises=ExchangeError("insufficient balance"),
        futures=(None, True),
    )

    await use_case.place(_command())

    assert stops.marked == []


async def test_an_opening_not_placeable_writes_no_stop_row() -> None:
    """Built before every write: nothing was sent, nothing is protected, nothing to void."""
    log: list[str] = []
    stops = SpyStops(log)
    use_case, *_ = _build(
        stops=stops,
        log=log,
        build_open_raises=OrderNotPlaceable(
            "too small",
            symbol="BTC_USDT",
            size=Decimal("0"),
            minimum=Decimal("1"),
            step=Decimal("1"),
        ),
    )

    await use_case.place(_command())

    assert stops.inserted == [] and stops.marked == []

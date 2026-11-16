"""``WatchProtectiveStops`` (subscriber-safety SS.7): every RESTING stop is read at the venue
by the user whose key placed it, and what became of it is decided under that user's pool
lock and committed on its own.

* a stop that FIRED has its fills booked the way a close's settle books them, under the
  stop's allocation, on a new FILLED attempt whose cause is STOP, with the stop marked FIRED
  and a WARNING ``protective stop fired``, all in one transaction;
* fills that sum to less than the ledger's net are not booked yet: the rest is not
  published, and the stop is read again;
* a stop that is gone with no fills is marked GONE and books nothing;
* a failure whose outcome is unknown leaves the stop RESTING, and one stop failing never
  stops the others.

The venue is read OUTSIDE the pool lock, and the decision re-checks the stop is still
RESTING after the lock is taken.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.ports import (
    ExchangeError,
    FillRecord,
    OwnedStop,
    ReservationSnapshot,
    StopFired,
    StopNotResting,
    StopReading,
    StopRests,
)
from strategy_manager.execution.application.watch_protective_stops import (
    WatchProtectiveStops,
    WatchResult,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionCause,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.fill import Fill
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency
from tests.allocation.fakes import RecordedModes
from tests.execution.fakes import OneRegistry

NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
USER = UUID("0a1b2c3d-0000-4000-8000-0000000e0e0e")
OTHER_USER = UUID("0a1b2c3d-0000-4000-8000-0000000e0e0f")
STRATEGY_ID = uuid4()
# The ledger and the stop carry the alert's spelling; the venue's own is bare.
SYMBOL = "DOGEUSDT.P"
USD_RATE = Decimal("1")
STOP_ORDER_ID = "STOP-ORDER-1"


class Log:
    """One ordered record of everything with a side effect or a lock."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


class Stops:
    """``ProtectiveStopRepositoryPort`` over a dict, with the owner of each row."""

    def __init__(self, log: Log) -> None:
        self.rows: dict[UUID, tuple[UUID, ProtectiveStop]] = {}
        self.listed = 0
        self._log = log
        self.mark_users: list[UUID] = []

    def add(self, user: UUID, stop: ProtectiveStop) -> None:
        self.rows[stop.execution_attempt_id] = (user, stop)

    async def resting_of_every_user(self) -> list[OwnedStop]:
        self.listed += 1
        return [
            OwnedStop(user_id=user, stop=stop)
            for user, stop in self.rows.values()
            if stop.status is StopStatus.RESTING
        ]

    async def for_attempt(self, user_id: UUID, attempt_id: UUID) -> ProtectiveStop | None:
        owner, stop = self.rows.get(attempt_id, (None, None))
        return stop if owner == user_id else None

    async def mark(
        self,
        user_id: UUID,
        attempt_id: UUID,
        status: StopStatus,
        venue_stop_id: str | None = None,
    ) -> None:
        self.mark_users.append(user_id)
        owner, stop = self.rows[attempt_id]
        assert owner == user_id
        self.rows[attempt_id] = (owner, _with_status(stop, status))
        self._log(f"stop.mark {status.value}")

    async def insert(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError

    async def record_trigger_price(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError

    def status_of(self, stop: ProtectiveStop) -> StopStatus:
        return self.rows[stop.execution_attempt_id][1].status


def _with_status(stop: ProtectiveStop, status: StopStatus) -> ProtectiveStop:
    from dataclasses import replace

    return replace(stop, status=status)


class Attempts:
    def __init__(self, log: Log) -> None:
        self.openings: dict[UUID, ExecutionAttempt] = {}
        self.inserted: list[tuple[UUID, ExecutionAttempt]] = []
        self.users: list[UUID] = []
        self._log = log

    async def get(self, user_id: UUID, attempt_id: UUID) -> ExecutionAttempt:
        self.users.append(user_id)
        return self.openings[attempt_id]

    async def insert(self, user_id: UUID, attempt: ExecutionAttempt) -> None:
        self.inserted.append((user_id, attempt))
        self._log("attempt.insert")

    async def mark_placed(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError

    async def mark_filled(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError

    async def mark_failed(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError


class Reservations:
    def __init__(self, log: Log) -> None:
        self.users: list[UUID] = []
        self._log = log

    async def get_for_update(self, user_id: UUID, reservation_id: UUID) -> ReservationSnapshot:
        self.users.append(user_id)
        self._log("reservation.lock")
        return ReservationSnapshot(
            id=reservation_id,
            strategy_id=STRATEGY_ID,
            signal_id=uuid4(),
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            amount=Decimal("20"),
            status="FILLED",
            mode=Mode.LIVE,
            expires_at=NOW,
        )

    async def mark(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError


class Held:
    def __init__(self, log: Log) -> None:
        self.net: dict[UUID, Decimal] = {}
        self.asked: list[tuple[UUID, UUID, str]] = []
        self._log = log

    async def net_base(self, user_id: UUID, allocation_id: UUID, base_currency: str) -> Decimal:
        self.asked.append((user_id, allocation_id, base_currency))
        self._log("held")
        return self.net[allocation_id]


class Recorder:
    def __init__(self, log: Log, raises: Exception | None = None) -> None:
        self.records: list[FillRecord] = []
        self._log = log
        self._raises = raises

    async def record(self, fill: FillRecord) -> None:
        if self._raises is not None:
            raise self._raises
        self.records.append(fill)
        self._log("ledger.record")


class Rates:
    def __init__(self) -> None:
        self.asked: list[Currency] = []

    async def usd_rate(self, currency: Currency) -> Decimal:
        self.asked.append(currency)
        return USD_RATE


class PoolLock:
    def __init__(self, log: Log) -> None:
        self.acquired: list[tuple[UUID, str, str, str]] = []
        self._log = log

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self.acquired.append((user_id, exchange, venue, settlement_currency))
        self._log("lock")


class Leaving:
    def __init__(self, log: Log) -> None:
        self.ended: list[tuple[UUID, UUID, str, str, str]] = []
        self._log = log

    async def end_if_flat(
        self, user_id: UUID, strategy_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> bool:
        self.ended.append((user_id, strategy_id, exchange, venue, settlement_currency))
        self._log("leaving.end_if_flat")
        return False


class UnitOfWork:
    def __init__(self, log: Log) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log("commit")

    async def rollback(self) -> None:
        self._log("rollback")


class VenueExchange:
    """``ExchangePort`` as the watcher uses it: ``read_stop``, scripted per stop."""

    is_live = True
    exchange = "bybit"
    venues = frozenset({"usdt-m"})

    def __init__(self, log: Log, readings: dict[UUID, StopReading | Exception]) -> None:
        self._log = log
        self._readings = readings
        self.reads: list[tuple[UUID, str]] = []

    async def read_stop(self, stop: ProtectiveStop, parent_client_order_id: str) -> StopReading:
        self.reads.append((stop.id, parent_client_order_id))
        self._log("read")
        answer = self._readings[stop.execution_attempt_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Registry:
    def __init__(self, exchange: VenueExchange) -> None:
        self.exchange = exchange
        self.pools: list[tuple[str, str]] = []

    def for_pool(self, exchange: str, venue: str) -> VenueExchange:
        self.pools.append((exchange, venue))
        return self.exchange


class Rig:
    def __init__(self, *, recorder_raises: Exception | None = None) -> None:
        self.log = Log()
        self.stops = Stops(self.log)
        self.attempts = Attempts(self.log)
        self.reservations = Reservations(self.log)
        self.held = Held(self.log)
        self.recorder = Recorder(self.log, recorder_raises)
        self.rates = Rates()
        self.pool_lock = PoolLock(self.log)
        self.leaving = Leaving(self.log)
        self.modes = RecordedModes()
        self.readings: dict[UUID, StopReading | Exception] = {}
        self.exchange = VenueExchange(self.log, self.readings)
        self.registry = Registry(self.exchange)
        self.mode_exchanges = OneRegistry(registry=self.registry)  # type: ignore[arg-type]
        self.opened_for: list[UUID] = []
        self.failing_owners: set[UUID] = set()

    @asynccontextmanager
    async def _exchanges_for(self, user_id: UUID) -> AsyncIterator[OneRegistry]:
        self.opened_for.append(user_id)
        if user_id in self.failing_owners:
            raise RuntimeError(f"the vault key of {user_id} does not open")
        self.log("exchanges.open")
        yield self.mode_exchanges

    def use_case(self) -> WatchProtectiveStops:
        return WatchProtectiveStops(
            stops=self.stops,  # type: ignore[arg-type]
            attempts=self.attempts,  # type: ignore[arg-type]
            reservations=self.reservations,  # type: ignore[arg-type]
            held=self.held,  # type: ignore[arg-type]
            fill_recorder=self.recorder,  # type: ignore[arg-type]
            usd_rates=self.rates,
            pool_lock=self.pool_lock,
            leaving=self.leaving,
            allocation_modes=self.modes,
            exchanges_for=self._exchanges_for,  # type: ignore[arg-type]
            unit_of_work=UnitOfWork(self.log),
        )

    def add_stop(
        self,
        *,
        user: UUID = USER,
        reading: StopReading | Exception,
        net: str = "76",
        side: OrderSide = OrderSide.BUY,
    ) -> ProtectiveStop:
        """A RESTING stop of ``user`` with the opening attempt it protects, the ledger's
        net of its allocation, and what the venue will answer about it."""
        allocation, attempt_id = uuid4(), uuid4()
        stop = ProtectiveStop(
            id=uuid4(),
            execution_attempt_id=attempt_id,
            allocation_id=allocation,
            exchange="bybit",
            venue="usdt-m",
            symbol=SYMBOL,
            position_side=PositionSide.LONG if side is OrderSide.BUY else PositionSide.SHORT,
            stop_loss_pct=Decimal("10"),
            trigger_price=Decimal("0.0597"),
            status=StopStatus.RESTING,
            venue_stop_id=STOP_ORDER_ID,
        )
        self.stops.add(user, stop)
        self.attempts.openings[attempt_id] = ExecutionAttempt(
            id=attempt_id,
            reservation_id=allocation,
            closes_allocation_id=None,
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            symbol=SYMBOL,
            side=side,
            quantity=Decimal("76"),
            quote_amount=None,
            leverage=Decimal("3"),
            status=ExecutionStatus.FILLED,
            origin=ExecutionOrigin.SYSTEM,
            client_order_id=f"open-{attempt_id}",
        )
        self.held.net[allocation] = Decimal(net) if side is OrderSide.BUY else -Decimal(net)
        self.readings[attempt_id] = reading
        return stop


def _fill(
    quantity: str = "76", fill_id: str = "EX-1", price: str = "0.0597", fee: str = "0.0025"
) -> Fill:
    return Fill(
        exchange_order_id=STOP_ORDER_ID,
        exchange_fill_id=fill_id,
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        fee_currency="USDT",
        filled_at=NOW,
    )


def _fired(*fills: Fill) -> StopFired:
    return StopFired(exchange_order_id=STOP_ORDER_ID, fills=list(fills))


def _messages(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == level]


# ---- a stop that still rests -------------------------------------------------------


async def test_a_stop_that_still_rests_is_left_alone() -> None:
    rig = Rig()
    stop = rig.add_stop(reading=StopRests())

    result = await rig.use_case().watch()

    assert result == WatchResult(read=1)
    assert rig.stops.status_of(stop) is StopStatus.RESTING
    # Nothing was decided, so no lock, no write and no transaction to end.
    assert rig.log.lines == ["exchanges.open", "read"]
    assert rig.attempts.inserted == []
    assert rig.recorder.records == []


async def test_every_resting_stop_is_read_with_one_system_query() -> None:
    rig = Rig()
    rig.add_stop(reading=StopRests())
    rig.add_stop(reading=StopRests())
    rig.add_stop(user=OTHER_USER, reading=StopRests())

    result = await rig.use_case().watch()

    assert rig.stops.listed == 1
    assert result.read == 3


async def test_a_stop_that_is_not_resting_is_never_read() -> None:
    rig = Rig()
    stop = rig.add_stop(reading=StopRests())
    rig.stops.rows[stop.execution_attempt_id] = (USER, _with_status(stop, StopStatus.GONE))

    result = await rig.use_case().watch()

    assert result == WatchResult()
    assert rig.opened_for == []
    assert rig.exchange.reads == []


# ---- a stop that fired --------------------------------------------------------------


async def test_a_fired_stop_books_its_fills_under_its_allocation_with_cause_stop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    stop = rig.add_stop(reading=_fired(_fill("46", "EX-1"), _fill("30", "EX-2", price="0.0596")))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=1, fired=1)

    # The attempt that carries the fills.
    [(attempt_user, attempt)] = rig.attempts.inserted
    assert attempt_user == USER
    assert attempt.cause is ExecutionCause.STOP
    assert attempt.origin is ExecutionOrigin.SYSTEM
    assert attempt.status is ExecutionStatus.FILLED
    assert attempt.closes_allocation_id == stop.allocation_id
    assert attempt.reservation_id is None
    assert attempt.client_order_id == f"stop-{stop.id}"
    assert attempt.exchange_order_id == STOP_ORDER_ID
    assert attempt.side is OrderSide.SELL
    assert attempt.quantity == Decimal("76")
    assert (attempt.exchange, attempt.venue, attempt.settlement_currency) == (
        "bybit",
        "usdt-m",
        "USDT",
    )
    assert attempt.symbol == SYMBOL
    assert attempt.signal_id is None and attempt.delivery_id is None

    # One ledger row per fill, in the shape a close's settle gives it.
    assert [
        (r.user_id, r.strategy_id, r.allocation_id, r.execution_attempt_id, r.side)
        for r in rig.recorder.records
    ] == [(USER, STRATEGY_ID, stop.allocation_id, attempt.id, "SELL")] * 2
    assert [
        (r.exchange_fill_id, r.quantity, r.price, r.fee, r.fee_currency, r.notional)
        for r in rig.recorder.records
    ] == [
        ("EX-1", Decimal("46"), Decimal("0.0597"), Decimal("0.0025"), "USDT", Decimal("2.7462")),
        ("EX-2", Decimal("30"), Decimal("0.0596"), Decimal("0.0025"), "USDT", Decimal("1.788")),
    ]
    assert all(r.exchange_order_id == STOP_ORDER_ID for r in rig.recorder.records)
    assert all(r.usd_rate_at_fill == USD_RATE for r in rig.recorder.records)
    assert rig.rates.asked == [Currency.USDT]

    # The stop is FIRED, the leaving subscription is ended if flat, and the WARNING names
    # the user, the symbol and the attempt.
    assert rig.stops.status_of(stop) is StopStatus.FIRED
    assert rig.leaving.ended == [(USER, STRATEGY_ID, "bybit", "usdt-m", "USDT")]
    [warning] = _messages(caplog, logging.WARNING)
    assert warning.startswith("protective stop fired")
    assert str(USER) in warning and SYMBOL in warning and str(stop.execution_attempt_id) in warning


async def test_a_fired_stop_is_booked_in_one_transaction_under_the_pool_lock() -> None:
    """The venue is read first, outside the lock. Then the pool lock, then the row locks,
    and one commit that carries the attempt, the fills, the mark and the leaving end."""
    rig = Rig()
    rig.add_stop(reading=_fired(_fill()))

    await rig.use_case().watch()

    assert rig.log.lines == [
        "exchanges.open",
        "read",
        "lock",
        "held",
        "reservation.lock",
        "attempt.insert",
        "ledger.record",
        "stop.mark FIRED",
        "leaving.end_if_flat",
        "commit",
    ]
    assert rig.pool_lock.acquired == [(USER, "bybit", "usdt-m", "USDT")]


async def test_a_fired_short_is_booked_as_a_buy() -> None:
    rig = Rig()
    rig.add_stop(reading=_fired(_fill()), side=OrderSide.SELL)

    result = await rig.use_case().watch()

    assert result.fired == 1
    [(_, attempt)] = rig.attempts.inserted
    assert attempt.side is OrderSide.BUY
    assert [r.side for r in rig.recorder.records] == ["BUY"]


async def test_the_ledger_is_read_in_the_base_currency_of_the_markets_own_spelling() -> None:
    """The stop carries TradingView's ``DOGEUSDT.P``; the ledger's base currency is DOGE."""
    rig = Rig()
    stop = rig.add_stop(reading=_fired(_fill()))

    await rig.use_case().watch()

    assert rig.held.asked == [(USER, stop.allocation_id, "DOGE")]


async def test_the_mode_the_allocation_opened_in_chooses_the_exchanges() -> None:
    rig = Rig()
    stop = rig.add_stop(reading=StopRests())

    await rig.use_case().watch()

    assert rig.modes.asked == [(USER, stop.allocation_id)]
    assert rig.mode_exchanges.asked == [Mode.LIVE]
    assert rig.registry.pools == [("bybit", "usdt-m")]
    # The venue is asked by the OPENING's own client order id, how Bybit finds its stop.
    assert rig.exchange.reads == [(stop.id, f"open-{stop.execution_attempt_id}")]


async def test_fills_short_of_the_ledgers_net_are_not_booked_yet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The rest is not published: booking part of it would leave the ledger holding a
    position the venue no longer has, and the stop could never be booked whole."""
    rig = Rig()
    stop = rig.add_stop(reading=_fired(_fill("46")))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=1, waiting=1)
    assert rig.stops.status_of(stop) is StopStatus.RESTING
    assert rig.attempts.inserted == [] and rig.recorder.records == []
    [warning] = _messages(caplog, logging.WARNING)
    assert "not all published" in warning
    assert str(USER) in warning and SYMBOL in warning and str(stop.execution_attempt_id) in warning
    # The lock the decision took is released by ending the (empty) transaction.
    assert rig.log.lines[-1] == "commit"
    assert "stop.mark FIRED" not in rig.log.lines


async def test_a_fired_stop_with_no_published_fill_waits_the_same_way(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    stop = rig.add_stop(reading=_fired())

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result.waiting == 1
    assert rig.stops.status_of(stop) is StopStatus.RESTING
    assert rig.recorder.records == []
    assert len(_messages(caplog, logging.WARNING)) == 1


@pytest.mark.parametrize(
    ("net", "why"),
    [
        ("40", "more than the ledger holds"),
        ("0", "ledger holds none of it"),
    ],
)
async def test_fills_the_ledger_cannot_hold_are_refused_loudly_and_not_booked(
    caplog: pytest.LogCaptureFixture, net: str, why: str
) -> None:
    """Booking 76 against a ledger of 40 would flip the allocation to a short that never
    existed. Nothing is written; the stop stays RESTING and says so every tick."""
    rig = Rig()
    stop = rig.add_stop(reading=_fired(_fill("76")), net=net)

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=1, refused=1)
    assert rig.stops.status_of(stop) is StopStatus.RESTING
    assert rig.attempts.inserted == [] and rig.recorder.records == []
    [error] = _messages(caplog, logging.ERROR)
    assert why in error
    assert str(USER) in error and SYMBOL in error and str(stop.execution_attempt_id) in error
    assert rig.log.lines[-1] == "commit"


async def test_fills_the_ledger_holds_the_other_way_round_are_refused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stop of a long whose ledger shows a short: one of the two is wrong about a real
    position, and booking either way makes it worse."""
    rig = Rig()
    stop = rig.add_stop(reading=_fired(_fill("76")))
    rig.held.net[stop.allocation_id] = Decimal("-76")

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result.refused == 1
    assert rig.recorder.records == []
    [error] = _messages(caplog, logging.ERROR)
    assert "the other way" in error


# ---- a stop that is gone ------------------------------------------------------------


async def test_a_stop_gone_with_no_fills_is_marked_gone_and_books_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Runs 3, 4 and 6: the position closed by other means and took its stop with it."""
    rig = Rig()
    stop = rig.add_stop(reading=StopNotResting(), net="0")

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=1, gone=1)
    assert rig.stops.status_of(stop) is StopStatus.GONE
    assert rig.attempts.inserted == []
    assert rig.recorder.records == []
    assert rig.leaving.ended == []
    assert _messages(caplog, logging.WARNING) == []
    assert _messages(caplog, logging.ERROR) == []
    assert rig.log.lines == ["exchanges.open", "read", "lock", "held", "stop.mark GONE", "commit"]


async def test_a_stop_gone_while_the_ledger_still_holds_the_position_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cancelled by hand, say: the position is open and nothing protects it any more. The
    stop is still GONE (there is nothing left to watch), and the line is the only trace."""
    rig = Rig()
    stop = rig.add_stop(reading=StopNotResting(), net="76")

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result.gone == 1
    assert rig.stops.status_of(stop) is StopStatus.GONE
    [warning] = _messages(caplog, logging.WARNING)
    assert "without its stop" in warning
    assert str(USER) in warning and SYMBOL in warning and str(stop.execution_attempt_id) in warning
    assert rig.attempts.inserted == []


# ---- the decision is made under the lock, on a fresh read ----------------------------


@pytest.mark.parametrize("decided", [StopStatus.FIRED, StopStatus.GONE])
async def test_a_stop_another_run_decided_while_this_one_waited_for_the_lock_is_skipped(
    decided: StopStatus,
) -> None:
    rig = Rig()
    stop = rig.add_stop(reading=_fired(_fill()))
    original_acquire = rig.pool_lock.acquire

    async def decided_meanwhile(
        user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        await original_acquire(user_id, exchange, venue, settlement_currency)
        rig.stops.rows[stop.execution_attempt_id] = (USER, _with_status(stop, decided))

    rig.pool_lock.acquire = decided_meanwhile  # type: ignore[method-assign]

    result = await rig.use_case().watch()

    assert result == WatchResult(read=1, skipped=1)
    assert rig.stops.status_of(stop) is decided
    assert rig.attempts.inserted == [] and rig.recorder.records == []
    assert "stop.mark FIRED" not in rig.log.lines and "stop.mark GONE" not in rig.log.lines
    assert rig.log.lines[-1] == "commit"


# ---- failures ------------------------------------------------------------------------


async def test_an_ambiguous_failure_leaves_the_stop_resting_and_the_others_are_still_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    failing = rig.add_stop(reading=TimeoutError("venue read timed out"))
    fine = rig.add_stop(reading=_fired(_fill()))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=2, fired=1, failed=1)
    assert rig.stops.status_of(failing) is StopStatus.RESTING
    assert rig.stops.status_of(fine) is StopStatus.FIRED
    [error] = _messages(caplog, logging.ERROR)
    assert str(USER) in error and SYMBOL in error and str(failing.execution_attempt_id) in error
    assert "RESTING" in error
    # The failed stop's transaction was ended, so its locks cannot leak into the next.
    assert "rollback" in rig.log.lines
    assert rig.log.lines.index("rollback") < rig.log.lines.index("lock")


async def test_a_definitive_refusal_to_read_is_logged_and_leaves_the_stop_resting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    stop = rig.add_stop(reading=ExchangeError("Binance refused to read the stop (code=-2015)"))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=1, failed=1)
    assert rig.stops.status_of(stop) is StopStatus.RESTING
    [error] = _messages(caplog, logging.ERROR)
    assert str(stop.execution_attempt_id) in error


async def test_a_failure_while_booking_rolls_the_whole_stop_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The ledger write failed after the attempt was staged: nothing of it is committed,
    the stop stays RESTING, and the next tick books it whole."""
    rig = Rig(recorder_raises=RuntimeError("ledger down"))
    stop = rig.add_stop(reading=_fired(_fill()))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert result == WatchResult(read=1, failed=1)
    assert "commit" not in rig.log.lines
    assert rig.log.lines[-1] == "rollback"
    assert rig.stops.status_of(stop) is StopStatus.RESTING
    assert len(_messages(caplog, logging.ERROR)) == 1


async def test_a_user_whose_exchanges_cannot_be_opened_does_not_stop_another_users_stops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    blocked = rig.add_stop(user=OTHER_USER, reading=StopRests())
    served = rig.add_stop(user=USER, reading=_fired(_fill()))
    rig.failing_owners.add(OTHER_USER)

    with caplog.at_level(logging.INFO):
        result = await rig.use_case().watch()

    assert rig.stops.status_of(served) is StopStatus.FIRED
    assert rig.stops.status_of(blocked) is StopStatus.RESTING
    assert result.fired == 1 and result.failed == 1
    errors = _messages(caplog, logging.ERROR)
    assert len(errors) == 1 and str(OTHER_USER) in errors[0]


# ---- one user's key signs for that user alone ----------------------------------------


async def test_each_stop_is_read_and_booked_as_the_user_whose_it_is() -> None:
    rig = Rig()
    mine = rig.add_stop(user=USER, reading=_fired(_fill()))
    theirs = rig.add_stop(user=OTHER_USER, reading=_fired(_fill(fill_id="EX-9")))

    result = await rig.use_case().watch()

    assert result.fired == 2
    assert sorted(rig.opened_for) == sorted([USER, OTHER_USER])
    booked = {(user, attempt.closes_allocation_id) for user, attempt in rig.attempts.inserted}
    assert booked == {(USER, mine.allocation_id), (OTHER_USER, theirs.allocation_id)}
    assert {r.user_id for r in rig.recorder.records} == {USER, OTHER_USER}
    assert sorted(rig.reservations.users) == sorted([USER, OTHER_USER])
    assert sorted(user for user, *_ in rig.pool_lock.acquired) == sorted([USER, OTHER_USER])
    assert sorted(rig.stops.mark_users) == sorted([USER, OTHER_USER])


async def test_nothing_resting_opens_no_exchange_and_reads_nothing() -> None:
    rig = Rig()

    result = await rig.use_case().watch()

    assert result == WatchResult()
    assert rig.opened_for == [] and rig.log.lines == []

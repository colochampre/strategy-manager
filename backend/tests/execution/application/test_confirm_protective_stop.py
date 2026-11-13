"""``ConfirmProtectiveStop`` (subscriber-safety SS.5): after a live opening's fills are
recorded, the stop that rests for it is found by the opening's id and recorded; when none
rests, the position is closed at once; when the venue cannot be asked, the job retries.

The one outcome that must never happen is a protected position closed because the venue
timed out, and the one that must never be lost is a position left open without its stop.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
    NothingRecordedYet,
)
from strategy_manager.execution.application.confirm_protective_stop import (
    ConfirmProtectiveStop,
)
from strategy_manager.execution.application.ports import (
    ExchangeError,
    ReservationSnapshot,
    RestingStop,
)
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.execution.domain.protective_stop import (
    PositionSide,
    ProtectiveStop,
    StopStatus,
)
from strategy_manager.execution.infrastructure.exchange_registry import (
    VenueExchangeRegistry,
)
from strategy_manager.shared.domain.mode import Mode
from tests.allocation.fakes import RecordedModes
from tests.execution.fakes import OneRegistry

NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
OWNER = UUID("0a1b2c3d-0000-4000-8000-0000000e0e0e")
ATTEMPT_ID = uuid4()
ALLOCATION_ID = uuid4()
STRATEGY_ID = uuid4()
CLIENT_ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
# The attempt records the alert's spelling; the venue's own is bare.
SYMBOL = "DOGEUSDT.P"


def _attempt(side: OrderSide = OrderSide.BUY) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=ATTEMPT_ID,
        reservation_id=ALLOCATION_ID,
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
        client_order_id=CLIENT_ORDER_ID,
    )


class FakeStops:
    def __init__(self, status: StopStatus | None, log: list[str]) -> None:
        self.status = status
        self.log = log
        self.marked: list[tuple[UUID, UUID, StopStatus, str | None]] = []

    async def insert(self, user_id: UUID, stop: ProtectiveStop) -> None:  # pragma: no cover
        raise NotImplementedError

    async def for_attempt(self, user_id: UUID, attempt_id: UUID) -> ProtectiveStop | None:
        if self.status is None:
            return None
        return ProtectiveStop(
            id=uuid4(),
            execution_attempt_id=attempt_id,
            allocation_id=ALLOCATION_ID,
            exchange="bybit",
            venue="usdt-m",
            symbol=SYMBOL,
            position_side=PositionSide.LONG,
            stop_loss_pct=Decimal("10"),
            trigger_price=Decimal("0.059706"),
            status=self.status,
        )

    async def mark(
        self,
        user_id: UUID,
        attempt_id: UUID,
        status: StopStatus,
        venue_stop_id: str | None = None,
    ) -> None:
        self.marked.append((user_id, attempt_id, status, venue_stop_id))
        self.log.append(f"stop.mark {status.value}")


class FakeAttempts:
    def __init__(self, attempt: ExecutionAttempt) -> None:
        self._attempt = attempt
        self.users: list[UUID] = []

    async def insert(self, user_id: UUID, attempt: ExecutionAttempt) -> None:  # pragma: no cover
        raise NotImplementedError

    async def get(self, user_id: UUID, attempt_id: UUID) -> ExecutionAttempt:
        self.users.append(user_id)
        return self._attempt

    async def mark_placed(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError

    async def mark_filled(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError

    async def mark_failed(self, *args: object) -> None:  # pragma: no cover
        raise NotImplementedError


class FakeReservations:
    def __init__(self) -> None:
        self.users: list[UUID] = []

    async def get_for_update(self, user_id: UUID, reservation_id: UUID) -> ReservationSnapshot:
        self.users.append(user_id)
        return ReservationSnapshot(
            id=ALLOCATION_ID,
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


class FakeExchange:
    is_live = True
    exchange = "bybit"
    venues = frozenset({"usdt-m"})

    def __init__(self, answer: RestingStop | None, raises: Exception | None = None) -> None:
        self._answer = answer
        self._raises = raises
        self.asked: list[tuple[str, str]] = []

    async def find_resting_stop(self, client_order_id: str, symbol: str) -> RestingStop | None:
        self.asked.append((client_order_id, symbol))
        if self._raises is not None:
            raise self._raises
        return self._answer

    async def place(self, order: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def build_open_order(self, spec: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def build_close_order(self, spec: object) -> object:  # pragma: no cover
        raise NotImplementedError

    async def fetch_fills(self, *args: object) -> list[object]:  # pragma: no cover
        raise NotImplementedError


class SpyCloser:
    """``ClosePosition`` as this use case sees it. ``log`` receives ``"close"`` and the
    commit count at the moment it is called, which is what proves the ``FAILED`` mark is
    staged for the close's own commit and not committed by itself."""

    def __init__(self, log: list[str], raises: Exception | None = None) -> None:
        self.commands: list[CloseCommand] = []
        self._log = log
        self._raises = raises

    async def close(self, command: CloseCommand) -> CloseResult:
        self.commands.append(command)
        self._log.append("close")
        if self._raises is not None:
            raise self._raises
        return CloseResult(
            status="PLACED",
            execution_attempt_id=uuid4(),
            base_size=Decimal("76"),
            exchange_order_id="BY-CLOSE-1",
        )


class SpyCommit:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log.append("commit")


class Rig:
    def __init__(
        self,
        *,
        status: StopStatus | None = StopStatus.PENDING,
        answer: RestingStop | None = None,
        exchange_raises: Exception | None = None,
        close_raises: Exception | None = None,
        side: OrderSide = OrderSide.BUY,
        mode: Mode = Mode.LIVE,
    ) -> None:
        self.log: list[str] = []
        self.stops = FakeStops(status, self.log)
        self.attempts = FakeAttempts(_attempt(side))
        self.reservations = FakeReservations()
        self.exchange = FakeExchange(answer, exchange_raises)
        self.modes = RecordedModes(mode)
        self.asked: list[Mode] = []
        self.closer = SpyCloser(self.log, close_raises)
        self.use_case = ConfirmProtectiveStop(
            stops=self.stops,
            attempts=self.attempts,  # type: ignore[arg-type]
            reservations=self.reservations,
            exchanges=OneRegistry(
                VenueExchangeRegistry([self.exchange]),  # type: ignore[list-item]
                self.asked,
            ),
            allocation_modes=self.modes,
            closer=self.closer,
            commit=SpyCommit(self.log),
        )


def _messages(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == level]


# ---- a stop that rests ----


async def test_a_resting_stop_is_recorded_with_the_id_the_venue_gave_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig(answer=RestingStop(venue_stop_id="STOP-1"))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "RESTING"
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.RESTING, "STOP-1")]
    assert rig.closer.commands == []
    assert rig.log == ["stop.mark RESTING", "commit"]
    [info] = _messages(caplog, logging.INFO)
    assert "STOP-1" in info and SYMBOL in info and str(ATTEMPT_ID) in info


async def test_the_stop_is_asked_for_by_the_openings_own_client_order_id_and_symbol() -> None:
    rig = Rig(answer=RestingStop(venue_stop_id="STOP-1"))

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.exchange.asked == [(CLIENT_ORDER_ID, SYMBOL)]


@pytest.mark.parametrize("mode", list(Mode))
async def test_the_stop_is_asked_of_the_adapter_of_the_mode_the_allocation_opened_in(
    mode: Mode,
) -> None:
    rig = Rig(answer=RestingStop(venue_stop_id="STOP-1"), mode=mode)

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.asked == [mode]
    assert rig.modes.asked == [(OWNER, ALLOCATION_ID)]


# ---- a stop that is already decided, or has nothing to find ----


@pytest.mark.parametrize(
    "status",
    [
        None,
        StopStatus.RESTING,
        StopStatus.FAILED,
        StopStatus.GONE,
        StopStatus.VOID,
        StopStatus.SIMULATED,
    ],
)
async def test_only_a_pending_stop_is_looked_for(status: StopStatus | None) -> None:
    """A redelivered job, or an attempt with no stop, asks the venue nothing and moves
    nothing."""
    rig = Rig(status=status)

    result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "SKIPPED"
    assert rig.exchange.asked == []
    assert rig.stops.marked == []
    assert rig.closer.commands == []
    assert rig.log == []
    assert rig.asked == []


# ---- a stop that is not there: the position is closed at once ----


async def test_no_resting_stop_fails_the_stop_and_closes_the_position_at_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig(answer=None)

    with caplog.at_level(logging.INFO):
        result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "CLOSING"
    assert result.close is not None and result.close.status == "PLACED"
    [command] = rig.closer.commands
    assert command == CloseCommand(
        user_id=OWNER,
        allocation_id=ALLOCATION_ID,
        strategy_id=STRATEGY_ID,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol=SYMBOL,
        side=OrderSide.SELL,
        signal_id=None,
        delivery_id=None,
        reference_price=None,
    )
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.FAILED, None)]
    [error] = _messages(caplog, logging.ERROR)
    assert str(OWNER) in error and SYMBOL in error and str(ATTEMPT_ID) in error


async def test_a_short_is_closed_by_buying_back() -> None:
    rig = Rig(answer=None, side=OrderSide.SELL)

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    [command] = rig.closer.commands
    assert command.side is OrderSide.BUY


async def test_the_failed_mark_rides_the_closes_own_commit_not_one_of_its_own() -> None:
    """Committed alone, a close that then failed to build would leave a FAILED row the
    retry skips, and a position nobody closes. Staged first, it commits with the close
    (and rolls back with it)."""
    rig = Rig(answer=None)

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.log == ["stop.mark FAILED", "close"]


async def test_a_close_that_cannot_be_built_leaves_the_stop_to_be_looked_for_again() -> None:
    """The unknown failure reaching the venue's rules propagates, so the job retries,
    and nothing was committed in the meantime."""
    rig = Rig(answer=None, close_raises=RuntimeError("venue rules unreadable"))

    with pytest.raises(RuntimeError, match="venue rules unreadable"):
        await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert "commit" not in rig.log


async def test_a_venue_refusal_is_a_stop_that_cannot_be_shown_to_rest(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig(exchange_raises=ExchangeError("no permission to read orders"))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "CLOSING"
    assert len(rig.closer.commands) == 1
    assert rig.stops.marked == [(OWNER, ATTEMPT_ID, StopStatus.FAILED, None)]
    [error] = _messages(caplog, logging.ERROR)
    assert "no permission to read orders" in error


async def test_an_unknown_failure_asking_the_venue_retries_and_closes_nothing() -> None:
    """A timeout is not a missing stop: closing a protected position over it is the
    failure this lookup exists to prevent."""
    rig = Rig(exchange_raises=TimeoutError("venue timed out"))

    with pytest.raises(TimeoutError):
        await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.stops.marked == []
    assert rig.closer.commands == []
    assert rig.log == []


async def test_a_flat_ledger_marks_the_stop_gone_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig(answer=None, close_raises=NothingRecordedYet("the ledger holds no DOGE"))

    with caplog.at_level(logging.INFO):
        result = await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert result.status == "GONE"
    assert rig.stops.marked == [
        (OWNER, ATTEMPT_ID, StopStatus.FAILED, None),
        (OWNER, ATTEMPT_ID, StopStatus.GONE, None),
    ]
    assert rig.log[-1] == "commit"
    [warning] = _messages(caplog, logging.WARNING)
    assert SYMBOL in warning and str(ATTEMPT_ID) in warning


async def test_the_users_own_rows_are_the_only_ones_read() -> None:
    rig = Rig(answer=None)

    await rig.use_case.confirm(OWNER, ATTEMPT_ID)

    assert rig.attempts.users == [OWNER]
    assert rig.reservations.users == [OWNER]

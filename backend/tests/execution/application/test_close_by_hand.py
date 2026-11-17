"""``CloseByHand`` (subscriber-safety SS.9): a user closes one of their own open positions
from the panel, and the worker sends it.

* one close through ``ClosePosition``, on the side opposite to the ledger's net, with the
  cause ``MANUAL``, no signal and no delivery, decided under the holder's pool lock;
* a close already SUBMITTED is never repeated, a FAILED one is tried again;
* an allocation the user does not hold (another user's, vanished) sends nothing and is an
  ERROR; a flat ledger sends nothing and is not;
* a refused close is an ERROR; an unexpected failure is an ERROR and is raised again, so the
  queue retries, after the transaction is rolled back.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.close_by_hand import CloseByHand
from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
    NothingRecordedYet,
)
from strategy_manager.execution.application.ports import StoppedPosition
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionCause,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide

USER = UUID("0a1b2c3d-0000-4000-8000-0000000e0e0e")
OTHER_USER = UUID("0a1b2c3d-0000-4000-8000-0000000e0e0f")
STRATEGY = uuid4()
# The ledger holds the alert's spelling; the venue's own is bare (``DOGEUSDT``).
SYMBOL = "DOGEUSDT.P"


class Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


class Positions:
    """``OwnPositionReaderPort``: what each ``(user, allocation)`` holds. Anything not
    registered under that exact pair reads as ``None``, as another user's does."""

    def __init__(self, log: Log) -> None:
        self.held: dict[tuple[UUID, UUID], StoppedPosition] = {}
        self._log = log

    async def position_of(self, user_id: UUID, allocation_id: UUID) -> StoppedPosition | None:
        self._log("read")
        return self.held.get((user_id, allocation_id))


class Attempts:
    def __init__(self) -> None:
        self.latest: dict[UUID, ExecutionAttempt] = {}

    async def latest_close_for(
        self, user_id: UUID, allocation_id: UUID
    ) -> ExecutionAttempt | None:
        return self.latest.get(allocation_id)


class PoolLock:
    def __init__(self, log: Log) -> None:
        self.acquired: list[tuple[UUID, str, str, str]] = []
        self._log = log

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self.acquired.append((user_id, exchange, venue, settlement_currency))
        self._log("lock")


class UnitOfWork:
    def __init__(self, log: Log) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log("commit")

    async def rollback(self) -> None:
        self._log("rollback")


class Closer:
    """``ClosePosition`` as the use case sees it. Like the real one it commits on every path
    that returns."""

    def __init__(self, log: Log, uow: UnitOfWork) -> None:
        self.commands: list[CloseCommand] = []
        self.answer: CloseResult | Exception = CloseResult(
            status="PLACED",
            execution_attempt_id=uuid4(),
            base_size=Decimal("76"),
            exchange_order_id="ORDER-1",
        )
        self._log = log
        self._uow = uow

    async def close(self, command: CloseCommand) -> CloseResult:
        self._log("close")
        self.commands.append(command)
        if isinstance(self.answer, Exception):
            raise self.answer
        await self._uow.commit()
        return self.answer


class Rig:
    def __init__(self) -> None:
        self.log = Log()
        self.positions = Positions(self.log)
        self.attempts = Attempts()
        self.pool_lock = PoolLock(self.log)
        self.uow = UnitOfWork(self.log)
        self.closer = Closer(self.log, self.uow)
        self.opened_for: list[UUID] = []

    @asynccontextmanager
    async def _closer_for(self, user_id: UUID) -> AsyncIterator[Closer]:
        self.opened_for.append(user_id)
        yield self.closer

    def use_case(self) -> CloseByHand:
        return CloseByHand(
            positions=self.positions,
            closing_attempts=self.attempts,
            pool_lock=self.pool_lock,
            closer_for=self._closer_for,
            unit_of_work=self.uow,
        )

    def hold(self, *, net: str = "76", user: UUID = USER) -> StoppedPosition:
        position = StoppedPosition(
            user_id=user,
            allocation_id=uuid4(),
            strategy_id=STRATEGY,
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            symbol=SYMBOL,
            net_base=Decimal(net),
        )
        self.positions.held[(user, position.allocation_id)] = position
        return position

    def add_close(self, position: StoppedPosition, status: ExecutionStatus) -> None:
        self.attempts.latest[position.allocation_id] = ExecutionAttempt(
            id=uuid4(),
            reservation_id=None,
            closes_allocation_id=position.allocation_id,
            exchange=position.exchange,
            venue=position.venue,
            settlement_currency=position.settlement_currency,
            symbol=position.symbol,
            side=OrderSide.SELL,
            quantity=position.net_base,
            quote_amount=None,
            leverage=None,
            status=status,
            origin=ExecutionOrigin.SYSTEM,
            client_order_id=f"close-{position.allocation_id}",
        )


def _messages(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == level]


async def test_a_long_position_is_sold_with_the_cause_manual_and_no_signal() -> None:
    rig = Rig()
    position = rig.hold(net="76")

    sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is True
    assert rig.closer.commands == [
        CloseCommand(
            user_id=USER,
            allocation_id=position.allocation_id,
            strategy_id=STRATEGY,
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            # The spelling the allocation opened with, as the reader returned it.
            symbol=SYMBOL,
            side=OrderSide.SELL,
            signal_id=None,
            delivery_id=None,
            reference_price=None,
            cause=ExecutionCause.MANUAL,
        )
    ]
    assert rig.opened_for == [USER]


async def test_a_short_position_is_bought_back() -> None:
    rig = Rig()
    position = rig.hold(net="-76")

    await rig.use_case().close(USER, position.allocation_id)

    assert [command.side for command in rig.closer.commands] == [OrderSide.BUY]
    assert rig.closer.commands[0].cause is ExecutionCause.MANUAL


async def test_it_is_decided_under_the_holders_pool_lock() -> None:
    rig = Rig()
    position = rig.hold()

    await rig.use_case().close(USER, position.allocation_id)

    assert rig.pool_lock.acquired == [(USER, "bybit", "usdt-m", "USDT")]
    # The plain read finds the pool; the lock; the read again under it; then the close.
    assert rig.log.lines == ["read", "lock", "read", "close", "commit"]


async def test_another_users_allocation_sends_nothing_and_is_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    theirs = rig.hold(user=OTHER_USER)

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, theirs.allocation_id)

    assert sent is False
    assert rig.closer.commands == []
    assert rig.pool_lock.acquired == []
    [error] = _messages(caplog, logging.ERROR)
    assert str(theirs.allocation_id) in error
    assert str(USER) in error


async def test_a_vanished_allocation_sends_nothing_and_is_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    allocation_id = uuid4()

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, allocation_id)

    assert sent is False
    assert rig.closer.commands == []
    [error] = _messages(caplog, logging.ERROR)
    assert str(allocation_id) in error
    assert rig.log.lines[-1] in {"commit", "rollback"}


async def test_an_allocation_that_went_missing_under_the_lock_sends_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The first read found it; the read under the lock did not."""
    rig = Rig()
    position = rig.hold()
    reads = 0

    original = rig.positions.position_of

    async def vanishing(user_id: UUID, allocation_id: UUID) -> StoppedPosition | None:
        nonlocal reads
        reads += 1
        if reads == 2:
            return None
        return await original(user_id, allocation_id)

    rig.positions.position_of = vanishing  # type: ignore[method-assign]

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is False
    assert rig.closer.commands == []
    assert len(_messages(caplog, logging.ERROR)) == 1
    assert rig.log.lines[-1] in {"commit", "rollback"}


async def test_a_close_already_submitted_is_not_sent_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    position = rig.hold()
    rig.add_close(position, ExecutionStatus.SUBMITTED)

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is False
    assert rig.closer.commands == []
    assert rig.log.lines[-1] == "commit"
    assert _messages(caplog, logging.ERROR) == []


async def test_a_failed_close_is_tried_again() -> None:
    rig = Rig()
    position = rig.hold()
    rig.add_close(position, ExecutionStatus.FAILED)

    sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is True
    assert [command.allocation_id for command in rig.closer.commands] == [position.allocation_id]


async def test_a_flat_ledger_sends_nothing_and_is_not_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    position = rig.hold(net="0")

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is False
    assert rig.closer.commands == []
    assert _messages(caplog, logging.ERROR) == []
    assert any(str(position.allocation_id) in line for line in _messages(caplog, logging.INFO))
    assert rig.log.lines[-1] == "commit"


async def test_a_ledger_that_went_flat_inside_the_close_is_not_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    position = rig.hold()
    rig.closer.answer = NothingRecordedYet("flat")

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is False
    assert _messages(caplog, logging.ERROR) == []
    assert rig.log.lines[-1] == "commit"


async def test_a_refused_close_is_an_error(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    position = rig.hold()
    rig.closer.answer = CloseResult(
        status="FAILED",
        execution_attempt_id=uuid4(),
        base_size=Decimal("76"),
        error="insufficient position",
    )

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is False
    [error] = _messages(caplog, logging.ERROR)
    assert str(position.allocation_id) in error
    assert "insufficient position" in error


@pytest.mark.parametrize("status", ["NOT_CLOSABLE", "ALREADY_CLOSED_BY_STOP", "ALREADY_FLAT"])
async def test_dust_and_a_position_already_gone_are_not_errors(
    status: str, caplog: pytest.LogCaptureFixture
) -> None:
    rig = Rig()
    position = rig.hold()
    rig.closer.answer = CloseResult(
        status=status, execution_attempt_id=None, base_size=Decimal("0.0001")
    )

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().close(USER, position.allocation_id)

    assert sent is False
    assert _messages(caplog, logging.ERROR) == []


async def test_an_unexpected_failure_rolls_back_is_an_error_and_is_raised_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    position = rig.hold()
    rig.closer.answer = RuntimeError("venue timed out")

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError, match="venue timed out"):
        await rig.use_case().close(USER, position.allocation_id)

    [error] = _messages(caplog, logging.ERROR)
    assert str(position.allocation_id) in error
    # The lock is not carried past the failed decision.
    assert rig.log.lines[-1] == "rollback"


async def test_a_placed_close_is_a_warning_naming_who_and_what(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    position = rig.hold()

    with caplog.at_level(logging.INFO):
        await rig.use_case().close(USER, position.allocation_id)

    [warning] = _messages(caplog, logging.WARNING)
    for fact in (USER, position.allocation_id, SYMBOL):
        assert str(fact) in warning
    assert _messages(caplog, logging.ERROR) == []

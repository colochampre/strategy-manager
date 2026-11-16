"""``CloseStoppedPositions`` (subscriber-safety SS.8b): the reservation sweep closes, at
market, every open position held on a disabled or archived strategy.

* each position gets one close through ``ClosePosition``, on the side opposite to the
  ledger's net, with the cause ``SAFETY_CLOSE``, no signal and no delivery;
* it is decided under the holder's pool lock, after the strategy is read again as stopped;
* a close already SUBMITTED is never repeated, a FAILED one is tried again;
* one position failing never stops the others, and the failure is an ERROR;
* a flat ledger and dust are not errors.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.execution.application.close_position import (
    CloseCommand,
    CloseResult,
    NothingRecordedYet,
)
from strategy_manager.execution.application.close_stopped_positions import (
    CloseStoppedPositions,
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
OTHER_STRATEGY = uuid4()
# The ledger holds the alert's spelling; the venue's own is bare.
SYMBOL = "SOLUSDT.P"


class Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


class Stopped:
    """``StoppedPositionsReaderPort``: ``positions`` is what the listing returns and
    ``stopped`` the strategies read as stopped when asked again under the lock."""

    def __init__(self, log: Log) -> None:
        self.positions: list[StoppedPosition] = []
        self.stopped: set[UUID] = set()
        self.listing_raises: Exception | None = None
        self._log = log

    async def stopped_positions(self) -> list[StoppedPosition]:
        self._log("list")
        if self.listing_raises is not None:
            raise self.listing_raises
        return list(self.positions)

    async def is_stopped(self, strategy_id: UUID) -> bool:
        self._log("recheck")
        return strategy_id in self.stopped


class Attempts:
    def __init__(self) -> None:
        self.latest: dict[UUID, ExecutionAttempt] = {}
        self.asked: list[tuple[UUID, UUID]] = []

    async def latest_close_for(
        self, user_id: UUID, allocation_id: UUID
    ) -> ExecutionAttempt | None:
        self.asked.append((user_id, allocation_id))
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
    """``ClosePosition`` as the use case sees it, scripted per allocation. Like the real
    one it commits on every path that returns."""

    def __init__(self, log: Log, uow: UnitOfWork) -> None:
        self.commands: list[CloseCommand] = []
        self.answers: dict[UUID, CloseResult | Exception] = {}
        self._log = log
        self._uow = uow

    async def close(self, command: CloseCommand) -> CloseResult:
        self._log("close")
        self.commands.append(command)
        answer = self.answers.get(
            command.allocation_id,
            CloseResult(
                status="PLACED",
                execution_attempt_id=uuid4(),
                base_size=Decimal("0.5"),
                exchange_order_id="ORDER-1",
            ),
        )
        if isinstance(answer, Exception):
            raise answer
        await self._uow.commit()
        return answer


class Rig:
    def __init__(self) -> None:
        self.log = Log()
        self.stopped = Stopped(self.log)
        self.attempts = Attempts()
        self.pool_lock = PoolLock(self.log)
        self.uow = UnitOfWork(self.log)
        self.closer = Closer(self.log, self.uow)
        self.opened_for: list[UUID] = []
        self.failing_users: set[UUID] = set()

    @asynccontextmanager
    async def _closer_for(self, user_id: UUID) -> AsyncIterator[Closer]:
        self.opened_for.append(user_id)
        if user_id in self.failing_users:
            raise RuntimeError(f"the vault key of {user_id} does not open")
        yield self.closer

    def use_case(self) -> CloseStoppedPositions:
        return CloseStoppedPositions(
            stopped=self.stopped,
            closing_attempts=self.attempts,
            pool_lock=self.pool_lock,
            closer_for=self._closer_for,
            unit_of_work=self.uow,
        )

    def add(
        self,
        *,
        net: str = "0.5",
        user: UUID = USER,
        strategy: UUID = STRATEGY,
        still_stopped: bool = True,
    ) -> StoppedPosition:
        """A position the listing returns, and whether the strategy still reads stopped."""
        position = StoppedPosition(
            user_id=user,
            allocation_id=uuid4(),
            strategy_id=strategy,
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            symbol=SYMBOL,
            net_base=Decimal(net),
        )
        self.stopped.positions.append(position)
        if still_stopped:
            self.stopped.stopped.add(strategy)
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


async def test_a_long_position_on_a_stopped_strategy_is_sold_with_no_signal() -> None:
    rig = Rig()
    position = rig.add(net="0.5")

    sent = await rig.use_case().sweep()

    assert sent == 1
    assert rig.closer.commands == [
        CloseCommand(
            user_id=USER,
            allocation_id=position.allocation_id,
            strategy_id=STRATEGY,
            exchange="bybit",
            venue="usdt-m",
            settlement_currency="USDT",
            symbol=SYMBOL,
            side=OrderSide.SELL,
            signal_id=None,
            delivery_id=None,
            reference_price=None,
            cause=ExecutionCause.SAFETY_CLOSE,
        )
    ]


async def test_a_short_position_is_bought_back() -> None:
    rig = Rig()
    rig.add(net="-0.5")

    await rig.use_case().sweep()

    assert [command.side for command in rig.closer.commands] == [OrderSide.BUY]
    assert rig.closer.commands[0].cause is ExecutionCause.SAFETY_CLOSE
    assert rig.closer.commands[0].signal_id is None
    assert rig.closer.commands[0].delivery_id is None


async def test_each_position_is_decided_under_its_holders_pool_lock_after_a_recheck() -> None:
    rig = Rig()
    rig.add()

    await rig.use_case().sweep()

    assert rig.pool_lock.acquired == [(USER, "bybit", "usdt-m", "USDT")]
    # The plain listing first; then the lock, the recheck and the close, in that order.
    assert rig.log.lines == ["list", "lock", "recheck", "close", "commit"]


async def test_each_users_close_is_signed_by_that_users_own_exchanges() -> None:
    rig = Rig()
    rig.add(user=USER)
    rig.add(user=OTHER_USER)
    rig.add(user=USER)

    await rig.use_case().sweep()

    assert sorted(rig.opened_for) == sorted([USER, OTHER_USER])
    assert [command.user_id for command in rig.closer.commands].count(USER) == 2
    assert [command.user_id for command in rig.closer.commands].count(OTHER_USER) == 1


async def test_a_strategy_enabled_again_under_the_lock_is_not_closed() -> None:
    """The listing was a plain read: the strategy may have been enabled before the lock
    was won. A close then would stop a running strategy's position."""
    rig = Rig()
    rig.add(still_stopped=False)

    sent = await rig.use_case().sweep()

    assert sent == 0
    assert rig.closer.commands == []
    # The lock is given back: nothing else commits it.
    assert rig.log.lines == ["list", "lock", "recheck", "commit"]


async def test_a_close_already_submitted_is_not_sent_again() -> None:
    rig = Rig()
    position = rig.add()
    rig.add_close(position, ExecutionStatus.SUBMITTED)

    sent = await rig.use_case().sweep()

    assert sent == 0
    assert rig.closer.commands == []
    assert rig.attempts.asked == [(USER, position.allocation_id)]
    assert rig.log.lines[-1] == "commit"


async def test_a_failed_close_is_tried_again() -> None:
    rig = Rig()
    position = rig.add()
    rig.add_close(position, ExecutionStatus.FAILED)

    sent = await rig.use_case().sweep()

    assert sent == 1
    assert [command.allocation_id for command in rig.closer.commands] == [position.allocation_id]


async def test_a_sent_close_is_a_warning_naming_who_what_and_where(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    position = rig.add()

    with caplog.at_level(logging.INFO):
        await rig.use_case().sweep()

    [warning] = _messages(caplog, logging.WARNING)
    for fact in (USER, position.allocation_id, STRATEGY, SYMBOL):
        assert str(fact) in warning
    assert _messages(caplog, logging.ERROR) == []


async def test_one_position_raising_does_not_stop_the_next_and_is_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    broken = rig.add()
    fine = rig.add()
    rig.closer.answers[broken.allocation_id] = RuntimeError("venue timed out")

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().sweep()

    assert sent == 1
    assert [command.allocation_id for command in rig.closer.commands] == [
        broken.allocation_id,
        fine.allocation_id,
    ]
    [error] = _messages(caplog, logging.ERROR)
    for fact in (USER, broken.allocation_id, STRATEGY, SYMBOL):
        assert str(fact) in error
    # The failed decision ended its transaction, so its lock is not carried to the next.
    assert "rollback" in rig.log.lines


async def test_a_user_whose_exchanges_cannot_open_does_not_stop_the_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    rig.failing_users.add(USER)
    stuck = rig.add(user=USER)
    other = rig.add(user=OTHER_USER)

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().sweep()

    assert sent == 1
    assert [command.allocation_id for command in rig.closer.commands] == [other.allocation_id]
    [error] = _messages(caplog, logging.ERROR)
    assert str(USER) in error
    assert str(stuck.allocation_id) in error


async def test_a_refused_close_is_an_error(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    position = rig.add()
    rig.closer.answers[position.allocation_id] = CloseResult(
        status="FAILED",
        execution_attempt_id=uuid4(),
        base_size=Decimal("0.5"),
        error="insufficient position",
    )

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().sweep()

    assert sent == 0
    [error] = _messages(caplog, logging.ERROR)
    assert str(position.allocation_id) in error
    assert "insufficient position" in error


async def test_a_flat_ledger_is_not_an_error(caplog: pytest.LogCaptureFixture) -> None:
    rig = Rig()
    position = rig.add()
    rig.closer.answers[position.allocation_id] = NothingRecordedYet("flat")

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().sweep()

    assert sent == 0
    assert _messages(caplog, logging.ERROR) == []
    # Nothing was committed by the closer, so the lock is given back here.
    assert rig.log.lines[-1] in {"commit", "rollback"}


@pytest.mark.parametrize("status", ["NOT_CLOSABLE", "ALREADY_CLOSED_BY_STOP", "ALREADY_FLAT"])
async def test_dust_and_a_position_already_gone_are_not_errors(
    status: str, caplog: pytest.LogCaptureFixture
) -> None:
    rig = Rig()
    position = rig.add()
    rig.closer.answers[position.allocation_id] = CloseResult(
        status=status, execution_attempt_id=None, base_size=Decimal("0.0001")
    )

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().sweep()

    assert sent == 0
    assert _messages(caplog, logging.ERROR) == []


async def test_nothing_stopped_sends_nothing() -> None:
    rig = Rig()

    sent = await rig.use_case().sweep()

    assert sent == 0
    assert rig.log.lines == ["list"]


async def test_a_failing_listing_is_an_error_and_rolls_back(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = Rig()
    rig.stopped.listing_raises = RuntimeError("db down")

    with caplog.at_level(logging.INFO):
        sent = await rig.use_case().sweep()

    assert sent == 0
    assert len(_messages(caplog, logging.ERROR)) == 1
    assert rig.log.lines == ["list", "rollback"]

"""Decision 25, tasks 5b.7-5b.9 at the handler level: what
``ProcessSignalHandler`` itself records around orders and closes, on top of
what ``PlaceOrder`` / ``ClosePosition`` record (rows 9-15, tested in
``tests/execution/application``).

Two things live in the handler and nowhere else:

* row 18, a spot REVERSE whose new side cannot be held, written after the
  close is placed (decision 26, design.md section E);
* the ABSENCE of a write on replays (rows 19-20): the FAILED-reverse
  replay and the idempotent close replay report a prior result and must
  never record a second, different outcome.

Fakes throughout; the durable and terminal-guard behaviour runs on real
PostgreSQL in ``tests/signals/infrastructure/test_order_outcomes_integration.py``.
"""

from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.execution.application.close_position import CloseResult
from strategy_manager.execution.domain.execution_attempt import (
    ExecutionAttempt,
    ExecutionOrigin,
    ExecutionStatus,
)
from strategy_manager.execution.domain.order import OrderSide
from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.domain.outcome import SignalOutcome
from tests.signals.application.test_process_signal import (
    FakeClosingAttemptsPort,
    SpyAdvisoryLock,
    SpyClosePosition,
    SpyPlaceOrder,
    _allocate_capital,
    _holdable_reverse_context,
    _process_signal_handler,
)
from tests.signals.fakes import RecordingSignalOutcomes


class Timeline:
    """One shared, ordered log of what the handler asked its collaborators
    to do, so a test can prove an outcome was staged BEFORE a given commit."""

    def __init__(self) -> None:
        self.log: list[str] = []


class TimelineOutcomes(RecordingSignalOutcomes):
    def __init__(self, timeline: Timeline) -> None:
        super().__init__()
        self._timeline = timeline

    async def record(self, signal_id: UUID, outcome: SignalOutcome) -> None:
        self._timeline.log.append(f"outcome.{outcome.status.value.lower()}")
        await super().record(signal_id, outcome)


class TimelineCommit:
    def __init__(self, timeline: Timeline) -> None:
        self._timeline = timeline

    async def commit(self) -> None:
        self._timeline.log.append("commit")


def _spot_short_reverse_context() -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol="BTC_USDT",
        price=Decimal("50000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),  # long -> short on SPOT: not holdable
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )


def _existing_close(status: ExecutionStatus, allocation_id: UUID) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=uuid4(),
        reservation_id=None,
        closes_allocation_id=allocation_id,
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="ETHUSDT.P",
        side=OrderSide.SELL,
        quantity=Decimal("1"),
        quote_amount=None,
        leverage=None,
        status=status,
        origin=ExecutionOrigin.SYSTEM,
        client_order_id="client-1",
        error="rejected by venue" if status is ExecutionStatus.FAILED else None,
    )


# ---- 5b.7: the close reaches the signal ------------------------------------


async def test_a_close_carries_the_signal_it_acts_on() -> None:
    close_position = SpyClosePosition()
    signal_id = uuid4()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="ETHUSDT.P",
        price=Decimal("2000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # long -> flat: RELEASES
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
    )

    await handler.handle(signal_id)

    assert [c.signal_id for c in close_position.calls] == [signal_id]


async def test_a_reverse_close_carries_the_signal_it_acts_on() -> None:
    close_position = SpyClosePosition()
    signal_id = uuid4()
    handler = _process_signal_handler(
        context=_holdable_reverse_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
    )

    await handler.handle(signal_id)

    assert [c.signal_id for c in close_position.calls] == [signal_id]


# ---- row 18: a spot REVERSE whose new side cannot be held ------------------


async def test_a_spot_short_reverse_ends_rejected_after_its_close_is_placed() -> None:
    timeline = Timeline()
    outcomes = TimelineOutcomes(timeline)
    signal_id = uuid4()
    handler = _process_signal_handler(
        context=_spot_short_reverse_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),  # PLACED
        outcomes=outcomes,
        commit=TimelineCommit(timeline),
    )

    result = await handler.handle(signal_id)

    assert result.executed is True
    assert result.refused is not None
    [(recorded_id, outcome)] = outcomes.calls
    assert recorded_id == signal_id
    assert outcome.reason == "REVERSE_NEW_SIDE_UNHOLDABLE"
    assert outcome.status.value == "REJECTED"
    assert outcome.detail is not None
    assert result.refused in outcome.detail
    assert "close was submitted" in outcome.detail
    assert "spot cannot hold the new short" in outcome.detail
    # staged, then the handler's own commit (the close's commit already ran)
    assert timeline.log == ["outcome.rejected", "commit"]


async def test_a_spot_short_reverse_whose_close_is_refused_adds_no_second_outcome() -> None:
    """The refused close (rows 13/14) already ended the signal, in
    ``ClosePosition``, with the CLOSE's code. Row 18 must not queue a second,
    different outcome behind it."""
    for status in ("FAILED", "NOT_CLOSABLE"):
        outcomes = RecordingSignalOutcomes()
        handler = _process_signal_handler(
            context=_spot_short_reverse_context(),
            allocate_capital=_allocate_capital(SpyAdvisoryLock()),
            place_order=SpyPlaceOrder(),
            close_position=SpyClosePosition(
                result=CloseResult(
                    status=status,
                    execution_attempt_id=None,
                    base_size=Decimal("1"),
                    error="refused",
                )
            ),
            outcomes=outcomes,
        )

        result = await handler.handle(uuid4())

        assert result.failed == "refused", status
        assert outcomes.calls == [], status


async def test_a_holdable_reverse_records_nothing_in_the_handler() -> None:
    """The open half is still to come in the continuation, so no row-18
    outcome exists for a holdable REVERSE; the close's own PROCESSING comes
    from ``ClosePosition``."""
    outcomes = RecordingSignalOutcomes()
    handler = _process_signal_handler(
        context=_holdable_reverse_context(),
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
        outcomes=outcomes,
    )

    result = await handler.handle(uuid4())

    assert result.executed is True and result.refused is None
    assert outcomes.calls == []


async def test_a_replayed_spot_short_reverse_records_the_same_outcome_again() -> None:
    """A redelivery finds the close already committed (not FAILED), skips the
    close, and re-reports. The row-18 outcome it stages must be IDENTICAL to
    the first delivery's, so the terminal guard treats it as a silent repeat
    rather than a differing second outcome."""
    context = _spot_short_reverse_context()
    assert context.prior_reservation_id is not None
    signal_id = uuid4()
    first = RecordingSignalOutcomes()
    second = RecordingSignalOutcomes()
    first_handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=SpyClosePosition(),
        outcomes=first,
    )
    replay_close = SpyClosePosition()
    second_handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=replay_close,
        closing_attempts=FakeClosingAttemptsPort(
            latest=_existing_close(ExecutionStatus.SUBMITTED, context.prior_reservation_id)
        ),
        outcomes=second,
    )

    await first_handler.handle(signal_id)
    await second_handler.handle(signal_id)

    assert replay_close.calls == []
    assert len(first.calls) == 1
    assert second.calls == first.calls


# ---- 5b.9, row 20: an idempotent close replay writes nothing ---------------


async def test_the_failed_reverse_close_replay_reports_it_without_a_second_outcome() -> None:
    """``handle()``'s "does NOT retry" branch re-reports an existing FAILED
    close. ``ClosePosition`` already ended the signal with the CLOSE's code
    the first time, so this branch must stay silent."""
    outcomes = RecordingSignalOutcomes()
    context = _holdable_reverse_context()
    assert context.prior_reservation_id is not None
    close_position = SpyClosePosition()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(
            latest=_existing_close(ExecutionStatus.FAILED, context.prior_reservation_id)
        ),
        outcomes=outcomes,
    )

    result = await handler.handle(uuid4())

    assert close_position.calls == []
    assert result.failed == "rejected by venue"
    assert outcomes.calls == []


async def test_an_idempotent_close_replay_writes_no_outcome() -> None:
    """A plain close whose earlier attempt already committed (not FAILED):
    the replay re-reports it and writes nothing, whatever the signal already
    holds."""
    outcomes = RecordingSignalOutcomes()
    context = SignalContext(
        strategy_id=uuid4(),
        symbol="ETHUSDT.P",
        price=Decimal("2000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),
        prior_reservation_id=uuid4(),
        settlement_currency="USDT",
    )
    assert context.prior_reservation_id is not None
    close_position = SpyClosePosition()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=SpyPlaceOrder(),
        close_position=close_position,
        closing_attempts=FakeClosingAttemptsPort(
            latest=_existing_close(ExecutionStatus.FILLED, context.prior_reservation_id)
        ),
        outcomes=outcomes,
    )

    result = await handler.handle(uuid4())

    assert close_position.calls == []
    assert result.executed is True
    assert outcomes.calls == []

"""Decision 27 (task 5b.11): a releasing signal with no position to release
(``_handle_releases``, ``prior_reservation_id is None``) used to return with no
log line and no outcome, leaving the signal ``ACCEPTED`` forever. It now logs
exactly one WARNING and ends ``REJECTED`` ``NO_POSITION_TO_CLOSE`` with that
message as the detail, on the commit that carries the refusal.

Behaviour is otherwise unchanged: nothing closes and nothing opens.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.signals.application.process_signal import SignalContext
from strategy_manager.signals.domain.outcome import SignalOutcome
from tests.signals.application.test_process_signal import (
    SpyAdvisoryLock,
    SpyClosePosition,
    SpyContinuationSeeder,
    SpyPlaceOrder,
    _allocate_capital,
    _process_signal_handler,
)
from tests.signals.fakes import RecordingSignalOutcomes

_LOGGER = "strategy_manager.signals.application.process_signal"


@dataclass
class _OrderingCommit:
    outcomes: RecordingSignalOutcomes
    staged_at_commit: list[int] = field(default_factory=list)

    async def commit(self) -> None:
        self.staged_at_commit.append(len(self.outcomes.calls))


def _close_context() -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol="ETHUSDT.P",
        price=Decimal("2000"),
        position_size=Decimal("0"),
        prior_position_size=Decimal("1"),  # long -> flat: RELEASES
        prior_reservation_id=None,
        settlement_currency="USDT",
    )


def _reverse_context() -> SignalContext:
    return SignalContext(
        strategy_id=uuid4(),
        symbol="ETHUSDT.P",
        price=Decimal("2000"),
        position_size=Decimal("-1"),
        prior_position_size=Decimal("1"),  # long -> short: REVERSE
        prior_reservation_id=None,
        settlement_currency="USDT",
    )


async def _run(context: SignalContext, caplog: pytest.LogCaptureFixture):  # type: ignore[no-untyped-def]
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    outcomes = RecordingSignalOutcomes()
    commit = _OrderingCommit(outcomes)
    close_position = SpyClosePosition()
    place_order = SpyPlaceOrder()
    seeder = SpyContinuationSeeder()
    handler = _process_signal_handler(
        context=context,
        allocate_capital=_allocate_capital(SpyAdvisoryLock()),
        place_order=place_order,
        close_position=close_position,
        open_after_close=seeder,
        outcomes=outcomes,
        commit=commit,
    )
    signal_id = uuid4()
    result = await handler.handle(signal_id)
    warnings = [r for r in caplog.records if r.name == _LOGGER and r.levelname == "WARNING"]
    return signal_id, result, outcomes, commit, warnings, close_position, place_order, seeder


async def test_a_close_with_no_position_logs_one_warning_and_ends_rejected(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _close_context()
    signal_id, result, outcomes, commit, warnings, close_position, place_order, seeder = (
        await _run(context, caplog)
    )

    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert str(signal_id) in message
    assert str(context.strategy_id) in message
    assert "ETHUSDT.P" in message
    assert outcomes.calls == [
        (signal_id, SignalOutcome.rejected("NO_POSITION_TO_CLOSE", message))
    ]
    assert commit.staged_at_commit == [1]  # staged before the one commit
    assert result.refused == message
    # behaviour unchanged: nothing closes, opens or seeds
    assert (close_position.calls, place_order.calls, seeder.calls) == ([], [], [])
    assert result.executed is False


async def test_a_reverse_with_no_position_says_the_new_side_was_not_opened(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = _reverse_context()
    signal_id, result, outcomes, commit, warnings, close_position, place_order, seeder = (
        await _run(context, caplog)
    )

    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "reverse" in message.lower()
    assert "not opened" in message
    assert outcomes.calls == [
        (signal_id, SignalOutcome.rejected("NO_POSITION_TO_CLOSE", message))
    ]
    assert commit.staged_at_commit == [1]
    assert (close_position.calls, place_order.calls, seeder.calls) == ([], [], [])
    assert result.executed is False


async def test_a_close_message_does_not_claim_a_reverse(
    caplog: pytest.LogCaptureFixture,
) -> None:
    *_, warnings, _, _, _ = await _run(_close_context(), caplog)

    assert "not opened" not in warnings[0].getMessage()

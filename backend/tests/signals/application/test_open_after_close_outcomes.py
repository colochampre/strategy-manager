"""Decision 25, task 5c.4: what ``OpenAfterClose.poll`` records when it
ABANDONS a signal (design.md § B rows ``SIGNAL_SUPERSEDED``,
``AWAITED_CLOSE_FAILED``, ``CONTINUATION_TIMED_OUT``).

Fakes only. Three properties matter and each has a test:

- every abandonment ends the signal ``REJECTED`` with its code, and the detail
  is the exact message logged for it;
- every write goes through ``record_unless_terminal``, never ``record``: the
  signal may already have ended (a REVERSE whose close was refused is
  ``REJECTED`` from ``signal.process``), and that must not WARN;
- nothing is written when nothing was abandoned, or when the signal is gone.

The commit is not visible here: ``poll`` never commits, the job handler's
trailing ``session.commit()`` does. The real-PostgreSQL proof that the write
survives that commit lives in ``test_open_after_close_outcomes_integration``.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from strategy_manager.execution.domain.execution_attempt import ExecutionStatus
from strategy_manager.signals.domain.outcome import SignalOutcome
from tests.signals.application.test_open_after_close import (
    MAX_SIGNAL_AGE_SECONDS,
    NOW,
    SETTLE_TIMEOUT_SECONDS,
    FakeClosingAttemptsPort,
    FakeSignalLookupPort,
    _attempt,
    _continuation,
    _job,
    _signal,
)
from tests.signals.fakes import RecordingSignalOutcomes

_LOGGER = "strategy_manager.signals.application.open_after_close"


def _abandonment_message(caplog: pytest.LogCaptureFixture) -> str:
    [record] = [r for r in caplog.records if r.name == _LOGGER and r.levelno >= 30]
    return record.getMessage()


async def test_a_superseded_signal_is_rejected_with_the_logged_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal = _signal()
    outcomes = RecordingSignalOutcomes()
    continuation, _, _, _ = _continuation(
        signals=FakeSignalLookupPort(signal=signal, newer=True), outcomes=outcomes
    )

    with caplog.at_level("WARNING", logger=_LOGGER):
        await continuation.poll(_job(signal.id, [uuid4()]))

    assert len(outcomes.unless_terminal_calls) == 1
    [(signal_id, outcome)] = outcomes.unless_terminal_calls
    assert signal_id == signal.id
    assert outcome == SignalOutcome.rejected("SIGNAL_SUPERSEDED", _abandonment_message(caplog))
    assert outcomes.calls == []  # never the warning path


async def test_an_awaited_close_that_failed_rejects_the_signal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    signal = _signal()
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FAILED, created_at=NOW
            )
        }
    )
    outcomes = RecordingSignalOutcomes()
    continuation, _, _, _ = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts, outcomes=outcomes
    )

    with caplog.at_level("ERROR", logger=_LOGGER):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert len(outcomes.unless_terminal_calls) == 1
    [(signal_id, outcome)] = outcomes.unless_terminal_calls
    assert signal_id == signal.id
    assert outcome == SignalOutcome.rejected("AWAITED_CLOSE_FAILED", _abandonment_message(caplog))
    assert outcomes.calls == []


async def test_a_signal_past_the_age_bound_after_its_closes_filled_is_timed_out(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Branch (3): the awaited close(s) settled FILLED, so for a REVERSE the
    position is already flat. The detail must say the open was not placed
    after the close(s) executed (decision 26), or the row cannot tell a
    partial REVERSE from a signal that did nothing."""
    signal = _signal(received_at=NOW - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS + 1))
    allocation_id = uuid4()
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FILLED, created_at=NOW
            )
        }
    )
    outcomes = RecordingSignalOutcomes()
    continuation, _, _, open_now = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts, outcomes=outcomes
    )

    with caplog.at_level("WARNING", logger=_LOGGER):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert open_now.calls == []
    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome == SignalOutcome.rejected("CONTINUATION_TIMED_OUT", _abandonment_message(caplog))
    assert outcome.detail is not None and "already settled" in outcome.detail
    assert outcomes.calls == []


async def test_a_vacuous_await_past_the_age_bound_does_not_claim_a_close_executed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The in-flight deferral awaits nothing specific; nothing of this
    signal's executed, so the detail must not say a close did."""
    signal = _signal(received_at=NOW - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS + 1))
    outcomes = RecordingSignalOutcomes()
    continuation, _, _, _ = _continuation(
        signals=FakeSignalLookupPort(signal=signal), outcomes=outcomes
    )

    with caplog.at_level("WARNING", logger=_LOGGER):
        await continuation.poll(_job(signal.id, []))

    assert len(outcomes.unless_terminal_calls) == 1
    [(_, outcome)] = outcomes.unless_terminal_calls
    assert outcome.reason == "CONTINUATION_TIMED_OUT"
    assert outcome.detail is not None and "already settled" not in outcome.detail


@pytest.mark.parametrize("age_bound", [False, True], ids=["settle-timeout", "age-bound"])
async def test_a_close_still_unsettled_past_either_bound_is_timed_out(
    caplog: pytest.LogCaptureFixture, age_bound: bool
) -> None:
    """Branch (4) covers BOTH bounds and both end with the same code, each
    with a detail that names the bound that actually fired."""
    signal = _signal(
        received_at=NOW - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS + 1) if age_bound else NOW
    )
    allocation_id = uuid4()
    created_at = NOW if age_bound else NOW - timedelta(seconds=SETTLE_TIMEOUT_SECONDS + 1)
    attempts = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id,
                status=ExecutionStatus.SUBMITTED,
                created_at=created_at,
            )
        }
    )
    outcomes = RecordingSignalOutcomes()
    continuation, _, queue, _ = _continuation(
        signals=FakeSignalLookupPort(signal=signal), attempts=attempts, outcomes=outcomes
    )

    with caplog.at_level("ERROR", logger=_LOGGER):
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert queue.enqueued == []
    assert len(outcomes.unless_terminal_calls) == 1
    [(signal_id, outcome)] = outcomes.unless_terminal_calls
    assert signal_id == signal.id
    assert outcome == SignalOutcome.rejected("CONTINUATION_TIMED_OUT", _abandonment_message(caplog))
    assert outcome.detail is not None
    if age_bound:
        assert f"{MAX_SIGNAL_AGE_SECONDS:.0f}s bound" in outcome.detail
    else:
        assert f"within {SETTLE_TIMEOUT_SECONDS:.0f}s" in outcome.detail
    assert outcomes.calls == []


async def test_a_deleted_signal_writes_nothing() -> None:
    outcomes = RecordingSignalOutcomes()
    continuation, _, _, _ = _continuation(
        signals=FakeSignalLookupPort(signal=None), outcomes=outcomes
    )

    await continuation.poll(_job(uuid4(), [uuid4()]))

    assert outcomes.calls == [] and outcomes.unless_terminal_calls == []


async def test_a_poll_that_abandons_nothing_writes_nothing() -> None:
    """Proceeding to ``open_now`` and rescheduling are not abandonments: the
    open half's own outcome is written by ``open_now`` (5c.5), never here."""
    signal = _signal()
    allocation_id = uuid4()
    filled = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.FILLED, created_at=NOW
            )
        }
    )
    waiting = FakeClosingAttemptsPort(
        closes={
            allocation_id: _attempt(
                allocation_id=allocation_id, status=ExecutionStatus.SUBMITTED, created_at=NOW
            )
        }
    )
    outcomes = RecordingSignalOutcomes()

    for attempts in (filled, waiting):
        continuation, _, _, _ = _continuation(
            signals=FakeSignalLookupPort(signal=signal), attempts=attempts, outcomes=outcomes
        )
        await continuation.poll(_job(signal.id, [allocation_id]))

    assert outcomes.calls == [] and outcomes.unless_terminal_calls == []

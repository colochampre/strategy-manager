"""``SignalOrderOutcomeRecorder`` maps the execution-side port onto
``SignalOutcomePort`` (decision 25, rows 9-15). Pure delegation, so a fake
outcome port is enough; the real-PostgreSQL behaviour lives in
``test_order_outcomes_integration.py``."""

from uuid import uuid4

from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.signal import SignalStatus
from strategy_manager.signals.infrastructure.order_outcome_recorder import (
    SignalOrderOutcomeRecorder,
)
from tests.signals.fakes import RecordingSignalOutcomes


async def test_processing_is_recorded_as_the_interim_status_never_processed() -> None:
    outcomes = RecordingSignalOutcomes()
    signal_id = uuid4()

    await SignalOrderOutcomeRecorder(outcomes).record_processing(signal_id)

    assert outcomes.calls == [(signal_id, SignalOutcome.processing())]
    assert outcomes.calls[0][1].status is SignalStatus.PROCESSING


async def test_a_rejection_carries_the_code_and_the_logged_message() -> None:
    outcomes = RecordingSignalOutcomes()
    signal_id = uuid4()

    await SignalOrderOutcomeRecorder(outcomes).record_rejected(
        signal_id, "ORDER_NOT_PLACEABLE", "too small"
    )

    assert outcomes.calls == [
        (signal_id, SignalOutcome.rejected("ORDER_NOT_PLACEABLE", "too small"))
    ]

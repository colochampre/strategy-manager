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


async def test_a_close_that_had_nothing_to_close_ends_processed_with_its_reason() -> None:
    """SS.7: ``ALREADY_CLOSED_BY_STOP`` and ``ALREADY_FLAT`` are not rejections. The
    delivery is done, and the reason says why nothing was sent or why the venue refused."""
    outcomes = RecordingSignalOutcomes()
    delivery_id = uuid4()

    await SignalOrderOutcomeRecorder(outcomes).record_processed(
        delivery_id, "ALREADY_CLOSED_BY_STOP", "the stop closed it"
    )

    [(recorded, outcome)] = outcomes.calls
    assert recorded == delivery_id
    assert outcome.status is SignalStatus.PROCESSED
    assert (outcome.reason, outcome.detail) == ("ALREADY_CLOSED_BY_STOP", "the stop closed it")


async def test_a_plain_processed_outcome_still_carries_no_reason() -> None:
    assert SignalOutcome.processed() == SignalOutcome(status=SignalStatus.PROCESSED)
    assert SignalOutcome.processed().reason is None


async def test_a_rejection_carries_the_code_and_the_logged_message() -> None:
    outcomes = RecordingSignalOutcomes()
    signal_id = uuid4()

    await SignalOrderOutcomeRecorder(outcomes).record_rejected(
        signal_id, "ORDER_NOT_PLACEABLE", "too small"
    )

    assert outcomes.calls == [
        (signal_id, SignalOutcome.rejected("ORDER_NOT_PLACEABLE", "too small"))
    ]

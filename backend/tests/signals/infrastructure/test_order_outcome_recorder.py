"""``SignalOrderOutcomeRecorder`` maps the execution-side port onto
``SignalOutcomePort`` (decision 25, rows 9-15). Pure delegation, so a fake
outcome port is enough; the real-PostgreSQL behaviour lives in
``test_order_outcomes_integration.py``."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.signal import IdempotencyKey, SignalStatus, WebhookSignal
from strategy_manager.signals.infrastructure.order_outcome_recorder import (
    SignalOrderOutcomeRecorder,
)
from tests.signals.fakes import RecordingSignalOutcomes

_T0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)
_STRATEGY = uuid4()


def _signal(position_size: str, received_at: datetime) -> WebhookSignal:
    return WebhookSignal(
        id=uuid4(),
        strategy_id=_STRATEGY,
        idempotency_key=IdempotencyKey(f"key-{uuid4()}"),
        action="sell",
        contracts=Decimal("1"),
        position_size=Decimal(position_size),
        price=Decimal("2"),
        symbol="DOGEUSDT.P",
        signal_type="test",
        raw_payload={},
        received_at=received_at,
    )


class _Signals:
    """The two reads that tell a reverse from a plain close, over an in-memory timeline."""

    def __init__(self, *signals: WebhookSignal) -> None:
        self._signals = list(signals)

    async def get_by_id(self, signal_id: UUID) -> WebhookSignal | None:
        return next((s for s in self._signals if s.id == signal_id), None)

    async def find_prior(
        self, strategy_id: UUID, symbol: str, before: datetime
    ) -> WebhookSignal | None:
        earlier = [
            s
            for s in self._signals
            if s.strategy_id == strategy_id
            and s.symbol == symbol
            and s.received_at is not None
            and s.received_at < before
        ]
        return max(earlier, key=lambda s: s.received_at or _T0, default=None)


@pytest.mark.parametrize(("prior", "current"), [("1", "0"), ("-1", "0")])
async def test_a_plain_close_refused_as_already_flat_ends_processed(
    prior: str, current: str
) -> None:
    """SS.7: nothing follows a plain close, so its delivery is done, and the reason says
    the venue position was already flat."""
    opening = _signal(prior, _T0)
    closing = _signal(current, _T0 + timedelta(hours=1))
    outcomes = RecordingSignalOutcomes()
    delivery_id = uuid4()

    recorder = SignalOrderOutcomeRecorder(outcomes, _Signals(opening, closing))
    await recorder.record_close_already_flat(
        delivery_id, closing.id, "the venue is flat"  # type: ignore[arg-type]
    )

    assert outcomes.calls == [
        (delivery_id, SignalOutcome.processed("ALREADY_FLAT", "the venue is flat"))
    ]


@pytest.mark.parametrize(("prior", "current"), [("1", "-1"), ("-2", "3")])
async def test_a_reverse_close_refused_as_already_flat_writes_nothing(
    prior: str, current: str
) -> None:
    """SS.7, owner decision 2026-11-13 (A): the reverse's open half still follows, once the
    stop watcher books the stop, and decides the outcome. A PROCESSED written here would
    block it through the terminal guard."""
    opening = _signal(prior, _T0)
    reverse = _signal(current, _T0 + timedelta(hours=1))
    outcomes = RecordingSignalOutcomes()

    recorder = SignalOrderOutcomeRecorder(outcomes, _Signals(opening, reverse))
    await recorder.record_close_already_flat(
        uuid4(), reverse.id, "the venue is flat"  # type: ignore[arg-type]
    )

    assert outcomes.calls == []


async def test_processing_is_recorded_as_the_interim_status_never_processed() -> None:
    outcomes = RecordingSignalOutcomes()
    signal_id = uuid4()

    await SignalOrderOutcomeRecorder(outcomes, _Signals()).record_processing(signal_id)

    assert outcomes.calls == [(signal_id, SignalOutcome.processing())]
    assert outcomes.calls[0][1].status is SignalStatus.PROCESSING


async def test_a_close_that_had_nothing_to_close_ends_processed_with_its_reason() -> None:
    """SS.7: ``ALREADY_CLOSED_BY_STOP`` and ``ALREADY_FLAT`` are not rejections. The
    delivery is done, and the reason says why nothing was sent or why the venue refused."""
    outcomes = RecordingSignalOutcomes()
    delivery_id = uuid4()

    await SignalOrderOutcomeRecorder(outcomes, _Signals()).record_processed(
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

    await SignalOrderOutcomeRecorder(outcomes, _Signals()).record_rejected(
        signal_id, "ORDER_NOT_PLACEABLE", "too small"
    )

    assert outcomes.calls == [
        (signal_id, SignalOutcome.rejected("ORDER_NOT_PLACEABLE", "too small"))
    ]

"""``SignalSettleOutcomeRecorder`` (decision 25, rows 16-17): what settle tells
a signal, and which signals it must stay silent for.

The one non-obvious rule is decision 26: a REVERSE's close fill writes NOTHING,
because its open half decides the final status. The recorder cannot be told
that by settle (``execution`` does not know signal kinds), so it derives the
kind the same way ``SignalContextAdapter`` does -- the signal's
``position_size`` against the prior signal's -- through ``PositionTransition``.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.application.ports import InsertOutcome
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.signal import IdempotencyKey, WebhookSignal
from strategy_manager.signals.infrastructure.settle_outcome_recorder import (
    SignalSettleOutcomeRecorder,
)
from tests.signals.fakes import RecordingSignalOutcomes

_T0 = datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
_STRATEGY = uuid4()
_SYMBOL = "STXUSDT_PERP"


def _signal(
    position_size: str, received_at: datetime, signal_id: UUID | None = None
) -> WebhookSignal:
    return WebhookSignal(
        id=signal_id or uuid4(),
        strategy_id=_STRATEGY,
        idempotency_key=IdempotencyKey(f"key-{uuid4()}"),
        action="sell",
        contracts=Decimal("1"),
        position_size=Decimal(position_size),
        price=Decimal("2"),
        symbol=_SYMBOL,
        signal_type="test",
        raw_payload={},
        received_at=received_at,
    )


class _FakeSignals:
    """Just the two reads the recorder makes, over an in-memory timeline."""

    def __init__(self, *signals: WebhookSignal) -> None:
        self._signals = list(signals)

    async def insert_or_get(self, signal: WebhookSignal) -> InsertOutcome:  # pragma: no cover
        raise NotImplementedError

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

    async def has_newer(  # pragma: no cover
        self, strategy_id: UUID, symbol: str, received_at: datetime
    ) -> bool:
        raise NotImplementedError


def _recorder(
    *signals: WebhookSignal,
) -> tuple[SignalSettleOutcomeRecorder, RecordingSignalOutcomes]:
    outcomes = RecordingSignalOutcomes()
    return SignalSettleOutcomeRecorder(outcomes, _FakeSignals(*signals)), outcomes


async def test_a_filled_open_ends_the_signal_processed() -> None:
    opening = _signal("1", _T0)
    recorder, outcomes = _recorder(opening)

    await recorder.record_open_filled(opening.id)  # type: ignore[arg-type]

    assert outcomes.calls == [(opening.id, SignalOutcome.processed())]


async def test_a_filled_plain_close_ends_the_signal_processed() -> None:
    opening = _signal("1", _T0)
    closing = _signal("0", _T0 + timedelta(hours=1))
    recorder, outcomes = _recorder(opening, closing)

    await recorder.record_close_filled(closing.id)  # type: ignore[arg-type]

    assert outcomes.calls == [(closing.id, SignalOutcome.processed())]


@pytest.mark.parametrize(("prior", "current"), [("1", "-1"), ("-2", "3")])
async def test_a_filled_reverse_close_writes_nothing(prior: str, current: str) -> None:
    """Decision 26: the open half decides. A PROCESSED written here would
    permanently block the open half's REJECTED through the terminal guard."""
    opening = _signal(prior, _T0)
    reverse = _signal(current, _T0 + timedelta(hours=1))
    recorder, outcomes = _recorder(opening, reverse)

    await recorder.record_close_filled(reverse.id)  # type: ignore[arg-type]

    assert outcomes.calls == []


async def test_a_close_of_a_signal_with_no_prior_is_not_a_reverse() -> None:
    """No prior signal reads as position 0, which classifies as an OPEN, not a
    REVERSE, so the recorder must not treat it as one."""
    only = _signal("1", _T0)
    recorder, outcomes = _recorder(only)

    await recorder.record_close_filled(only.id)  # type: ignore[arg-type]

    assert outcomes.calls == [(only.id, SignalOutcome.processed())]


async def test_a_never_placed_order_rejects_the_signal_with_its_detail() -> None:
    opening = _signal("1", _T0)
    recorder, outcomes = _recorder(opening)

    await recorder.record_never_placed(opening.id, "attempt X never reached the exchange")  # type: ignore[arg-type]

    assert outcomes.calls == [
        (
            opening.id,
            SignalOutcome.rejected(
                "ORDER_NEVER_REACHED_EXCHANGE", "attempt X never reached the exchange"
            ),
        )
    ]


async def test_a_reverse_whose_close_never_reached_the_exchange_is_rejected() -> None:
    """A refused close ends the REVERSE with the CLOSE's code (decision 26),
    unlike a filled one: nothing executed, so there is no open half to wait
    for."""
    opening = _signal("1", _T0)
    reverse = _signal("-1", _T0 + timedelta(hours=1))
    recorder, outcomes = _recorder(opening, reverse)

    await recorder.record_never_placed(reverse.id, "detail")  # type: ignore[arg-type]

    assert outcomes.calls == [
        (reverse.id, SignalOutcome.rejected("ORDER_NEVER_REACHED_EXCHANGE", "detail"))
    ]


async def test_a_close_for_an_unknown_signal_is_loud_not_silent() -> None:
    recorder, outcomes = _recorder()

    with pytest.raises(InvariantViolation):
        await recorder.record_close_filled(uuid4())

    assert outcomes.calls == []

"""Unit tests for the ``SignalOutcome`` value object (decision 25, design.md
"Addendum: signal outcomes" § D).

``SignalOutcome`` is constructed only through its named factories
(``processing()``, ``processed()``, ``rejected(reason, detail)``), so an
invalid combination -- ``REJECTED`` with no reason -- must be unbuildable
even through the dataclass constructor directly, ahead of the DB CHECK
constraint (migration 0025) that would otherwise be the only thing
catching it.
"""

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.signal import SignalStatus


def test_processing_factory_builds_processing_status_with_no_reason_or_detail() -> None:
    outcome = SignalOutcome.processing()

    assert outcome.status == SignalStatus.PROCESSING
    assert outcome.reason is None
    assert outcome.detail is None


def test_processed_factory_builds_processed_status_with_no_reason_or_detail() -> None:
    outcome = SignalOutcome.processed()

    assert outcome.status == SignalStatus.PROCESSED
    assert outcome.reason is None
    assert outcome.detail is None


def test_rejected_factory_stores_reason_and_detail() -> None:
    outcome = SignalOutcome.rejected("PAIR_NOT_ALLOWED", "ETHUSDT is not on the allowlist")

    assert outcome.status == SignalStatus.REJECTED
    assert outcome.reason == "PAIR_NOT_ALLOWED"
    assert outcome.detail == "ETHUSDT is not on the allowlist"


def test_rejected_factory_accepts_no_detail() -> None:
    outcome = SignalOutcome.rejected("UNTRADABLE_POOL")

    assert outcome.status == SignalStatus.REJECTED
    assert outcome.reason == "UNTRADABLE_POOL"
    assert outcome.detail is None


def test_rejected_factory_rejects_empty_reason() -> None:
    with pytest.raises(InvariantViolation):
        SignalOutcome.rejected("")


def test_direct_construction_of_rejected_with_no_reason_raises_invariant_violation() -> None:
    """The guard must live in the value object itself, not only in the
    ``rejected()`` factory -- bypassing the factory and constructing the
    dataclass directly must be equally unable to build an invalid
    combination (design.md § D: "cannot be built at all")."""

    with pytest.raises(InvariantViolation):
        SignalOutcome(status=SignalStatus.REJECTED, reason=None, detail=None)


def test_signal_outcome_is_frozen() -> None:
    outcome = SignalOutcome.processed()

    with pytest.raises(AttributeError):
        outcome.status = SignalStatus.REJECTED  # type: ignore[misc]

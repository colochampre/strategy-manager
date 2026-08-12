"""Unit tests for PositionTransition.classify.

Covers design.md § "position_size routes the signal": the five documented
transitions, plus an absent prior treated as 0.
"""

from decimal import Decimal

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.position_transition import (
    PositionTransition,
    TransitionEffect,
    TransitionKind,
)


def test_open_long_from_zero_to_positive_consumes() -> None:
    transition = PositionTransition.classify(Decimal("0"), Decimal("10"))

    assert transition.kind == TransitionKind.OPEN_LONG
    assert transition.effects == (TransitionEffect.CONSUMES,)


def test_open_short_from_zero_to_negative_consumes() -> None:
    transition = PositionTransition.classify(Decimal("0"), Decimal("-10"))

    assert transition.kind == TransitionKind.OPEN_SHORT
    assert transition.effects == (TransitionEffect.CONSUMES,)


def test_close_long_from_positive_to_zero_releases() -> None:
    transition = PositionTransition.classify(Decimal("10"), Decimal("0"))

    assert transition.kind == TransitionKind.CLOSE_LONG
    assert transition.effects == (TransitionEffect.RELEASES,)


def test_close_short_from_negative_to_zero_releases() -> None:
    transition = PositionTransition.classify(Decimal("-10"), Decimal("0"))

    assert transition.kind == TransitionKind.CLOSE_SHORT
    assert transition.effects == (TransitionEffect.RELEASES,)


def test_reverse_from_positive_to_negative_releases_then_consumes() -> None:
    transition = PositionTransition.classify(Decimal("10"), Decimal("-5"))

    assert transition.kind == TransitionKind.REVERSE
    assert transition.effects == (TransitionEffect.RELEASES, TransitionEffect.CONSUMES)


def test_reverse_from_negative_to_positive_releases_then_consumes() -> None:
    transition = PositionTransition.classify(Decimal("-10"), Decimal("5"))

    assert transition.kind == TransitionKind.REVERSE
    assert transition.effects == (TransitionEffect.RELEASES, TransitionEffect.CONSUMES)


def test_absent_prior_is_treated_as_zero() -> None:
    transition = PositionTransition.classify(None, Decimal("10"))

    assert transition.kind == TransitionKind.OPEN_LONG
    assert transition.effects == (TransitionEffect.CONSUMES,)


def test_unclassifiable_transition_raises_invariant_violation() -> None:
    with pytest.raises(InvariantViolation):
        PositionTransition.classify(Decimal("0"), Decimal("0"))

"""Classifies a signal's position-size transition into an intent and its
effect on pool capital (design.md § "position_size routes the signal").

``action`` alone cannot distinguish opening from closing a position (a
``buy`` may open a long or close a short); the transition in
``position_size`` carries the real intent. Only capital-*consuming* work
takes the advisory lock — releasing work can only increase availability and
can never over-allocate, so it is deliberately routed differently (slice 5).
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from strategy_manager.shared.domain.errors import InvariantViolation


class TransitionKind(StrEnum):
    """Every position transition this system recognises."""

    OPEN_LONG = "open_long"
    OPEN_SHORT = "open_short"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"
    REVERSE = "reverse"


class TransitionEffect(StrEnum):
    """Effect a transition has on pool capital."""

    CONSUMES = "consumes"
    RELEASES = "releases"


@dataclass(frozen=True, slots=True)
class PositionTransition:
    """The classified intent of a signal, plus its ordered effects on the pool."""

    kind: TransitionKind
    effects: tuple[TransitionEffect, ...]

    @classmethod
    def classify(cls, prior: Decimal | None, next_: Decimal) -> "PositionTransition":
        """Classify the move from ``prior`` to ``next_``. An absent prior
        (first-ever signal for a strategy/symbol pair) is treated as ``0``."""

        prior_value = prior if prior is not None else Decimal("0")

        if prior_value == 0 and next_ > 0:
            return cls(TransitionKind.OPEN_LONG, (TransitionEffect.CONSUMES,))
        if prior_value == 0 and next_ < 0:
            return cls(TransitionKind.OPEN_SHORT, (TransitionEffect.CONSUMES,))
        if prior_value > 0 and next_ == 0:
            return cls(TransitionKind.CLOSE_LONG, (TransitionEffect.RELEASES,))
        if prior_value < 0 and next_ == 0:
            return cls(TransitionKind.CLOSE_SHORT, (TransitionEffect.RELEASES,))
        if (prior_value > 0 and next_ < 0) or (prior_value < 0 and next_ > 0):
            return cls(
                TransitionKind.REVERSE,
                (TransitionEffect.RELEASES, TransitionEffect.CONSUMES),
            )

        raise InvariantViolation(
            f"unclassifiable position transition: {prior_value} -> {next_}"
        )

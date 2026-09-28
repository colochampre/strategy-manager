"""``SignalOutcome`` value object (decision 25, design.md "Addendum: signal
outcomes" § D).

A frozen VO carrying the final (or interim ``PROCESSING``) status a signal's
processing decided, importing no framework. Constructed only through its
named factories -- ``processing()``, ``processed()``, ``rejected(reason,
detail)`` -- but the invariant they exist to protect (a ``REJECTED`` outcome
without a reason cannot be represented) is enforced in ``__post_init__``
itself, ahead of migration 0025's own CHECK constraint, so bypassing the
factories and constructing the dataclass directly cannot build an invalid
combination either.
"""

from dataclasses import dataclass

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.signals.domain.signal import SignalStatus


@dataclass(frozen=True, slots=True)
class SignalOutcome:
    status: SignalStatus
    reason: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status == SignalStatus.REJECTED and not self.reason:
            raise InvariantViolation("a REJECTED signal outcome must carry a reason")

    @staticmethod
    def processing() -> "SignalOutcome":
        return SignalOutcome(status=SignalStatus.PROCESSING)

    @staticmethod
    def processed() -> "SignalOutcome":
        return SignalOutcome(status=SignalStatus.PROCESSED)

    @staticmethod
    def rejected(reason: str, detail: str | None = None) -> "SignalOutcome":
        return SignalOutcome(status=SignalStatus.REJECTED, reason=reason, detail=detail)

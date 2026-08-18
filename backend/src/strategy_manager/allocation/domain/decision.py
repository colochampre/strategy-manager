"""Pure allocation decision function (design.md § The ``AllocationDecision``
Algorithm). No framework imports, no I/O, no clock, no config — everything it
needs is passed in by the caller.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.rules import AllocationRules, FillMode
from strategy_manager.shared.domain.money import Money

_ZERO = Decimal("0")


class DecisionOutcome(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    SKIP = "SKIP"


class SkipReason(StrEnum):
    REQUEST_BELOW_MIN_ORDER_SIZE = "REQUEST_BELOW_MIN_ORDER_SIZE"
    NO_AVAILABILITY = "NO_AVAILABILITY"
    INSUFFICIENT_AVAILABILITY = "INSUFFICIENT_AVAILABILITY"
    PARTIAL_BELOW_MIN_ORDER_SIZE = "PARTIAL_BELOW_MIN_ORDER_SIZE"


@dataclass(frozen=True, slots=True)
class AllocationDecision:
    outcome: DecisionOutcome
    granted: Decimal
    skip_reason: SkipReason | None = None


def decide(pool: CapitalPool, requested: Money, rules: AllocationRules) -> AllocationDecision:
    """Evaluated strictly in order; the first match wins (design.md's ordered
    rules table). Guarantees: ``granted <= available`` and
    ``granted <= requested`` always; ``granted > 0`` iff the outcome is
    ``FULL`` or ``PARTIAL``; all arithmetic is exact ``Decimal``.
    """

    # Rule 1
    if requested.amount < rules.min_order_size:
        return AllocationDecision(
            DecisionOutcome.SKIP, _ZERO, SkipReason.REQUEST_BELOW_MIN_ORDER_SIZE
        )

    available = pool.available

    # Rule 2
    if available <= _ZERO:
        return AllocationDecision(DecisionOutcome.SKIP, _ZERO, SkipReason.NO_AVAILABILITY)

    # Rule 3
    if requested.amount <= available:
        return AllocationDecision(DecisionOutcome.FULL, requested.amount, None)

    # Rule 4
    if rules.fill_mode is FillMode.SKIP:
        return AllocationDecision(
            DecisionOutcome.SKIP, _ZERO, SkipReason.INSUFFICIENT_AVAILABILITY
        )

    # Rule 5
    if available < rules.min_order_size:
        return AllocationDecision(
            DecisionOutcome.SKIP, _ZERO, SkipReason.PARTIAL_BELOW_MIN_ORDER_SIZE
        )

    # Rule 6
    return AllocationDecision(DecisionOutcome.PARTIAL, available, None)

"""``Subscription`` aggregate and its legal state machine (multi-user design
AD3, tasks.md C.3; mirrors the ``subscriptions`` table of migration ``0031``).

A subscription is the only way to trade a strategy, its author included: a
user's share of their own pool for one strategy's market.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.domain.strategy import AllocationPercent


class SubscriptionStatus(StrEnum):
    """Mirrors the ``ck_subscriptions_status`` CHECK constraint."""

    ACTIVE = "ACTIVE"
    # Left while holding an open allocation of the strategy: no new openings,
    # and the position runs until the strategy closes it (decision 4).
    LEAVING = "LEAVING"
    ENDED = "ENDED"


# ENDED is terminal. A user who comes back gets a new subscription.
_LEGAL_TRANSITIONS: dict[SubscriptionStatus, frozenset[SubscriptionStatus]] = {
    SubscriptionStatus.ACTIVE: frozenset({SubscriptionStatus.LEAVING, SubscriptionStatus.ENDED}),
    SubscriptionStatus.LEAVING: frozenset({SubscriptionStatus.ENDED}),
    SubscriptionStatus.ENDED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Subscription:
    """Mirrors a row of ``subscriptions``. ``pool_id`` is the subscriber's own
    pool for the strategy's market; the database enforces both halves."""

    id: UUID
    user_id: UUID
    strategy_id: UUID
    pool_id: int
    allocation_percent: AllocationPercent
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE
    created_at: datetime | None = None
    left_at: datetime | None = None
    ended_at: datetime | None = None

    def leave(self, now: datetime) -> "Subscription":
        """Leaves while an open allocation still runs. Raises unless ACTIVE."""

        return replace(self._move_to(SubscriptionStatus.LEAVING), left_at=now)

    def end(self, now: datetime) -> "Subscription":
        """Ends it, from ACTIVE or LEAVING. A LEAVING one keeps its ``left_at``."""

        return replace(self._move_to(SubscriptionStatus.ENDED), ended_at=now)

    def change_share(self, allocation_percent: AllocationPercent) -> "Subscription":
        """A new share, for an ACTIVE subscription only: a LEAVING one takes no
        new openings, so a share would size nothing, and an ENDED one is over."""

        if self.status is not SubscriptionStatus.ACTIVE:
            raise InvariantViolation(
                f"only an ACTIVE subscription changes its share, this one is {self.status}"
            )
        return replace(self, allocation_percent=allocation_percent)

    def _move_to(self, new_status: SubscriptionStatus) -> "Subscription":
        if new_status not in _LEGAL_TRANSITIONS[self.status]:
            raise InvariantViolation(
                f"illegal subscription transition: {self.status} -> {new_status}"
            )
        return replace(self, status=new_status)

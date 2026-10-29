from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus

_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _subscription(status: SubscriptionStatus = SubscriptionStatus.ACTIVE) -> Subscription:
    return Subscription(
        id=uuid4(),
        user_id=uuid4(),
        strategy_id=uuid4(),
        pool_id=1,
        allocation_percent=AllocationPercent(Decimal("30")),
        status=status,
    )


def test_a_new_subscription_is_active() -> None:
    subscription = Subscription(
        id=uuid4(),
        user_id=uuid4(),
        strategy_id=uuid4(),
        pool_id=1,
        allocation_percent=AllocationPercent(Decimal("30")),
    )

    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.left_at is None
    assert subscription.ended_at is None


def test_an_active_subscription_leaves() -> None:
    subscription = _subscription()

    left = subscription.leave(_NOW)

    assert left.status is SubscriptionStatus.LEAVING
    assert left.left_at == _NOW
    assert left.ended_at is None
    assert subscription.status is SubscriptionStatus.ACTIVE


def test_an_active_subscription_ends() -> None:
    ended = _subscription().end(_NOW)

    assert ended.status is SubscriptionStatus.ENDED
    assert ended.ended_at == _NOW


def test_a_leaving_subscription_ends_and_keeps_when_it_left() -> None:
    left_at = datetime(2026, 10, 26, tzinfo=UTC)
    leaving = _subscription().leave(left_at)

    ended = leaving.end(_NOW)

    assert ended.status is SubscriptionStatus.ENDED
    assert ended.left_at == left_at
    assert ended.ended_at == _NOW


def test_an_active_subscription_changes_its_share() -> None:
    subscription = _subscription()

    changed = subscription.change_share(AllocationPercent(Decimal("45")))

    assert changed.allocation_percent == AllocationPercent(Decimal("45"))
    assert changed.status is SubscriptionStatus.ACTIVE
    assert subscription.allocation_percent == AllocationPercent(Decimal("30"))


@pytest.mark.parametrize("status", [SubscriptionStatus.LEAVING, SubscriptionStatus.ENDED])
def test_only_an_active_subscription_changes_its_share(status: SubscriptionStatus) -> None:
    subscription = _subscription(status)

    with pytest.raises(InvariantViolation, match="only an ACTIVE subscription"):
        subscription.change_share(AllocationPercent(Decimal("45")))


@pytest.mark.parametrize(
    ("status", "move"),
    [
        (SubscriptionStatus.LEAVING, "leave"),
        (SubscriptionStatus.ENDED, "leave"),
        (SubscriptionStatus.ENDED, "end"),
    ],
)
def test_any_other_move_raises(status: SubscriptionStatus, move: str) -> None:
    subscription = _subscription(status)

    with pytest.raises(InvariantViolation, match="illegal subscription transition"):
        getattr(subscription, move)(_NOW)

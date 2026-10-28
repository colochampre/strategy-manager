"""``EndLeavingSubscription``'s decision, against fakes (tasks.md C.6).

A LEAVING subscription ends once its user holds nothing of the strategy; every
other state is left as it is. The real lock and the real holding read are proven
against PostgreSQL in ``test_end_leaving_integration.py`` and with the settlement
in ``tests/signals/infrastructure/test_delivery_flow_integration.py``.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.end_leaving import EndLeavingSubscription
from strategy_manager.subscriptions.application.ports import Market
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus

_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
_LEFT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class _Subscriptions:
    def __init__(self, log: list[str], live: Subscription | None) -> None:
        self._log = log
        self._live = live
        self.updated: Subscription | None = None
        self.asked: list[tuple[UUID, UUID]] = []

    async def get_live_for_update(self, user_id: UUID, strategy_id: UUID) -> Subscription | None:
        self._log.append("get_live_for_update")
        self.asked.append((user_id, strategy_id))
        return self._live

    async def update(self, subscription: Subscription) -> None:
        self._log.append("update")
        self.updated = subscription


class _Allocations:
    def __init__(self, log: list[str], holds: bool) -> None:
        self._log = log
        self._holds = holds
        self.asked: list[tuple[UUID, UUID, Market]] = []

    async def holds_open_allocation(
        self, user_id: UUID, strategy_id: UUID, market: Market
    ) -> bool:
        self._log.append("holds_open_allocation")
        self.asked.append((user_id, strategy_id, market))
        return self._holds


class _Clock:
    def now(self) -> datetime:
        return _NOW


def _subscription(status: SubscriptionStatus) -> Subscription:
    return Subscription(
        id=uuid4(),
        user_id=uuid4(),
        strategy_id=uuid4(),
        pool_id=1,
        allocation_percent=AllocationPercent(Decimal("30")),
        status=status,
        left_at=_LEFT if status is SubscriptionStatus.LEAVING else None,
    )


def _build(
    live: Subscription | None, *, holds: bool
) -> tuple[EndLeavingSubscription, list[str], _Subscriptions, _Allocations]:
    log: list[str] = []
    subscriptions = _Subscriptions(log, live)
    allocations = _Allocations(log, holds)
    use_case = EndLeavingSubscription(subscriptions, allocations, _Clock())  # type: ignore[arg-type]
    return use_case, log, subscriptions, allocations


async def _run(use_case: EndLeavingSubscription, subscription: Subscription) -> bool:
    return await use_case.end_if_flat(
        subscription.user_id, subscription.strategy_id, "bybit", "usdt-m", "USDT"
    )


async def test_a_leaving_subscription_that_holds_nothing_ends_keeping_when_it_left() -> None:
    subscription = _subscription(SubscriptionStatus.LEAVING)
    use_case, log, subscriptions, allocations = _build(subscription, holds=False)

    ended = await _run(use_case, subscription)

    assert ended is True
    assert subscriptions.updated is not None
    assert subscriptions.updated.status is SubscriptionStatus.ENDED
    assert subscriptions.updated.ended_at == _NOW
    assert subscriptions.updated.left_at == _LEFT
    assert log == ["get_live_for_update", "holds_open_allocation", "update"]
    assert allocations.asked == [
        (subscription.user_id, subscription.strategy_id, ("bybit", "usdt-m", "USDT"))
    ]


async def test_a_leaving_subscription_that_still_holds_something_stays_leaving() -> None:
    subscription = _subscription(SubscriptionStatus.LEAVING)
    use_case, _, subscriptions, _ = _build(subscription, holds=True)

    ended = await _run(use_case, subscription)

    assert ended is False
    assert subscriptions.updated is None


async def test_an_active_subscription_is_left_alone_without_reading_the_holding() -> None:
    subscription = _subscription(SubscriptionStatus.ACTIVE)
    use_case, log, subscriptions, _ = _build(subscription, holds=False)

    ended = await _run(use_case, subscription)

    assert ended is False
    assert subscriptions.updated is None
    assert log == ["get_live_for_update"]


async def test_a_user_with_no_live_subscription_changes_nothing() -> None:
    subscription = _subscription(SubscriptionStatus.LEAVING)
    use_case, log, subscriptions, _ = _build(None, holds=False)

    ended = await _run(use_case, subscription)

    assert ended is False
    assert subscriptions.updated is None
    assert log == ["get_live_for_update"]
    assert subscriptions.asked == [(subscription.user_id, subscription.strategy_id)]

"""``Leave``'s order of operations, against fakes that record the calls.

The real lock is proven against PostgreSQL in ``test_subscriptions_router.py``;
this pins the ORDER the design requires (multi-user design AD3, lock order): the
pool's advisory lock first, then the row lock, and the open-allocation read only
after both.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.errors import (
    AuthorCannotLeave,
    SubscriptionNotFound,
)
from strategy_manager.subscriptions.application.leave import Leave
from strategy_manager.subscriptions.application.ports import Market, StrategyMarket
from strategy_manager.subscriptions.domain.subscription import Subscription, SubscriptionStatus

_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
_MARKET: Market = ("bybit", "usdt-m", "USDT")


class _Calls:
    def __init__(self) -> None:
        self.log: list[str] = []


class _Subscriptions:
    def __init__(self, calls: _Calls, subscription: Subscription) -> None:
        self._calls = calls
        self._subscription = subscription
        self.updated: Subscription | None = None

    async def get(self, user_id: UUID, subscription_id: UUID) -> Subscription | None:
        self._calls.log.append("get")
        mine = self._subscription.user_id == user_id and self._subscription.id == subscription_id
        return self._subscription if mine else None

    async def get_for_update(self, user_id: UUID, subscription_id: UUID) -> Subscription | None:
        self._calls.log.append("get_for_update")
        return self._subscription

    async def update(self, subscription: Subscription) -> None:
        self._calls.log.append("update")
        self.updated = subscription


class _Strategies:
    def __init__(self, strategy_id: UUID, author_id: UUID) -> None:
        self._strategy_id = strategy_id
        self._author_id = author_id

    async def find(self, strategy_id: UUID) -> StrategyMarket | None:
        return StrategyMarket(
            id=self._strategy_id, market=_MARKET, archived=False, author_id=self._author_id
        )


class _Allocations:
    def __init__(self, calls: _Calls, holds: bool) -> None:
        self._calls = calls
        self._holds = holds

    async def holds_open_allocation(
        self, user_id: UUID, strategy_id: UUID, market: Market
    ) -> bool:
        self._calls.log.append("holds_open_allocation")
        return self._holds


class _Lock:
    def __init__(self, calls: _Calls) -> None:
        self._calls = calls
        self.taken: tuple[UUID, str, str, str] | None = None

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self._calls.log.append("lock")
        self.taken = (user_id, exchange, venue, settlement_currency)


class _Commit:
    def __init__(self, calls: _Calls) -> None:
        self._calls = calls

    async def commit(self) -> None:
        self._calls.log.append("commit")


class _Clock:
    def now(self) -> datetime:
        return _NOW


def _leave(
    *, holds: bool, by_the_author: bool = False
) -> tuple[Leave, _Calls, _Subscriptions, _Lock, Subscription]:
    calls = _Calls()
    subscription = Subscription(
        id=uuid4(),
        user_id=uuid4(),
        strategy_id=uuid4(),
        pool_id=1,
        allocation_percent=AllocationPercent(Decimal("30")),
    )
    subscriptions = _Subscriptions(calls, subscription)
    lock = _Lock(calls)
    author_id = subscription.user_id if by_the_author else uuid4()
    use_case = Leave(
        subscriptions=subscriptions,
        strategies=_Strategies(subscription.strategy_id, author_id),
        allocations=_Allocations(calls, holds),
        pool_lock=lock,
        commit=_Commit(calls),
        clock=_Clock(),
    )
    return use_case, calls, subscriptions, lock, subscription


async def test_the_pool_lock_comes_before_the_row_lock_and_the_allocation_read() -> None:
    use_case, calls, subscriptions, lock, subscription = _leave(holds=True)

    left = await use_case.leave(subscription.user_id, subscription.id)

    assert calls.log == [
        "get",
        "lock",
        "get_for_update",
        "holds_open_allocation",
        "update",
        "commit",
    ]
    assert lock.taken == (subscription.user_id, *_MARKET)
    assert left.status is SubscriptionStatus.LEAVING
    assert subscriptions.updated == left


async def test_without_an_open_allocation_it_ends() -> None:
    use_case, _, subscriptions, _, subscription = _leave(holds=False)

    left = await use_case.leave(subscription.user_id, subscription.id)

    assert left.status is SubscriptionStatus.ENDED
    assert left.ended_at == _NOW
    assert subscriptions.updated == left


async def test_a_subscription_of_another_user_takes_no_lock_and_writes_nothing() -> None:
    use_case, calls, subscriptions, lock, subscription = _leave(holds=True)

    with pytest.raises(SubscriptionNotFound):
        await use_case.leave(uuid4(), subscription.id)

    assert calls.log == ["get"]
    assert lock.taken is None
    assert subscriptions.updated is None


async def test_the_author_cannot_leave_and_nothing_is_locked_or_written() -> None:
    """Owner decision 22: the author stays subscribed to their own strategy."""
    use_case, calls, subscriptions, lock, subscription = _leave(holds=False, by_the_author=True)

    with pytest.raises(AuthorCannotLeave):
        await use_case.leave(subscription.user_id, subscription.id)

    assert calls.log == ["get"]
    assert lock.taken is None
    assert subscriptions.updated is None

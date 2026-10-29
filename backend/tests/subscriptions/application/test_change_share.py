"""``ChangeShare`` leaves a trace of a real share change, and only of one.

The line moved here from ``UpdateStrategy`` when the share left the strategy
(C.4b): how much capital a user's subscription asks for is the same audit
question it was on the strategy.
"""

import logging
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.subscriptions.application.change_share import ChangeShare
from strategy_manager.subscriptions.domain.subscription import Subscription

_LOGGER = "strategy_manager.subscriptions.application.change_share"


class _Subscriptions:
    def __init__(self, subscription: Subscription) -> None:
        self._subscription = subscription

    async def get_for_update(self, user_id: UUID, subscription_id: UUID) -> Subscription | None:
        return self._subscription

    async def update(self, subscription: Subscription) -> None:
        self._subscription = subscription


class _Commit:
    def __init__(self, fails: bool = False) -> None:
        self._fails = fails

    async def commit(self) -> None:
        if self._fails:
            raise RuntimeError("commit failed")


def _subscription(share: str) -> Subscription:
    return Subscription(
        id=uuid4(),
        user_id=uuid4(),
        strategy_id=uuid4(),
        pool_id=1,
        allocation_percent=AllocationPercent(Decimal(share)),
    )


def _share_lines(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _LOGGER]


async def test_a_real_change_is_logged_with_the_ids_and_both_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscription = _subscription("30")
    use_case = ChangeShare(_Subscriptions(subscription), _Commit())

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await use_case.change(
            subscription.user_id, subscription.id, AllocationPercent(Decimal("45.5"))
        )

    lines = _share_lines(caplog)
    assert len(lines) == 1
    message = lines[0].getMessage()
    assert str(subscription.id) in message
    assert str(subscription.strategy_id) in message
    assert "from 30 to 45.5" in message


async def test_the_same_value_written_differently_is_not_a_change(
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscription = _subscription("33.5")
    use_case = ChangeShare(_Subscriptions(subscription), _Commit())

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        await use_case.change(
            subscription.user_id, subscription.id, AllocationPercent(Decimal("33.50"))
        )

    assert _share_lines(caplog) == []


async def test_a_change_that_never_commits_leaves_no_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscription = _subscription("30")
    use_case = ChangeShare(_Subscriptions(subscription), _Commit(fails=True))

    with caplog.at_level(logging.INFO, logger=_LOGGER), pytest.raises(RuntimeError):
        await use_case.change(
            subscription.user_id, subscription.id, AllocationPercent(Decimal("45.5"))
        )

    assert _share_lines(caplog) == []

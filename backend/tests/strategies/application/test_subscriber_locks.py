"""Archive and delete take the pool lock of EVERY live subscriber, in ascending
``pool_id`` order, and only then the row lock (multi-user tasks.md C.9, finding e).

Fakes share one event log, so a test reads the order in which the use case reached
the subscribers, the pool locks, the row lock and the commit. What a lock actually
serializes is proven on real PostgreSQL in ``test_subscriber_locks_concurrency.py``.
"""

import logging
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.application.archive_strategy import (
    ArchiveStrategy,
    OpenPosition,
    StillEnabled,
)
from strategy_manager.strategies.application.delete_strategy import DeleteStrategy
from strategy_manager.strategies.application.ports import (
    StrategyExposure,
    StrategyHistory,
    SubscriberPool,
)
from strategy_manager.strategies.application.subscriber_locks import SubscribersChanged
from strategy_manager.strategies.domain.allowed_pairs import AllowedPairs
from strategy_manager.strategies.domain.strategy import (
    AllocationPercent,
    AllocationPolicy,
    FillMode,
    Strategy,
)
from tests.owner import OWNER_ID
from tests.strategies.fakes import FakeSubscribers, author_pool

STRATEGY_ID = UUID("7256917a-9937-4a6c-b6d3-9cb2b4a9cedd")
USER_B = UUID("bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb")
USER_C = UUID("cccccccc-2222-4222-8222-cccccccccccc")
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
ARCHIVE_LOGGER = "strategy_manager.strategies.application.archive_strategy"
LOCKS_LOGGER = "strategy_manager.strategies.application.subscriber_locks"
MARKET = ("bybit", "usdt-m", "USDT")


def _strategy(**overrides: object) -> Strategy:
    policy = AllocationPolicy(
        exchange=Exchange.BYBIT,
        venue=Venue.USDT_M,
        settlement_currency=Currency.USDT,
        fill_mode=FillMode.PARTIAL,
        allocation_percent=AllocationPercent(Decimal("100")),
    )
    fields: dict[str, object] = {
        "id": STRATEGY_ID,
        "name": "Lock Me v1",
        "policy": policy,
        "author_id": OWNER_ID,
        "allowed_pairs": AllowedPairs(frozenset({"STXUSDT"})),
        "enabled": False,
    }
    fields.update(overrides)
    return Strategy(**fields)  # type: ignore[arg-type]


def _pool(pool_id: int, user_id: UUID, market: tuple[str, str, str] = MARKET) -> SubscriberPool:
    return SubscriberPool(pool_id=pool_id, user_id=user_id, pool=market)


class _Repository:
    def __init__(self, strategy: Strategy, events: list[str]) -> None:
        self.strategy = strategy
        self.events = events
        self.updated: list[Strategy] = []
        self.deleted: list[UUID] = []

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None:
        self.events.append("get_by_id")
        return self.strategy

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        self.events.append("get_by_id_for_update")
        return self.strategy

    async def update(self, strategy: Strategy) -> None:
        self.events.append("update")
        self.updated.append(strategy)

    async def delete(self, strategy_id: UUID) -> None:
        self.events.append("delete")
        self.deleted.append(strategy_id)


class _Lock:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.acquired: list[tuple[UUID, str, str, str]] = []

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        self.events.append("pool_lock")
        self.acquired.append((user_id, exchange, venue, settlement_currency))


class _Exposure:
    def __init__(self, answer: StrategyExposure | None = None) -> None:
        self.answer = answer or StrategyExposure(frozenset(), (), (), ())

    async def exposure(self, strategy_id: UUID, pool: tuple[str, str, str]) -> StrategyExposure:
        return self.answer


class _History:
    async def history(self, strategy_id: UUID) -> StrategyHistory:
        return StrategyHistory(0, 0, 0, 0, 0, 0, 0)


class _EnablementLog:
    async def list_for(self, strategy_id: UUID) -> list[object]:
        return []


class _Commit:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")


class _Clock:
    def now(self) -> datetime:
        return NOW


class Archiving:
    def __init__(
        self,
        subscribers: FakeSubscribers,
        *,
        strategy: Strategy | None = None,
        exposure: StrategyExposure | None = None,
    ) -> None:
        self.events: list[str] = []
        self.subscribers = subscribers
        subscribers._events = self.events  # noqa: SLF001 -- one shared event log
        self.repository = _Repository(strategy or _strategy(), self.events)
        self.lock = _Lock(self.events)
        self.use_case = ArchiveStrategy(
            repository=self.repository,  # type: ignore[arg-type]
            pool_lock=self.lock,
            subscribers=subscribers,
            exposure=_Exposure(exposure),
            commit=_Commit(self.events),
            clock=_Clock(),
        )


class Deleting:
    def __init__(self, subscribers: FakeSubscribers) -> None:
        self.events: list[str] = []
        subscribers._events = self.events  # noqa: SLF001 -- one shared event log
        self.repository = _Repository(_strategy(), self.events)
        self.lock = _Lock(self.events)
        self.use_case = DeleteStrategy(
            repository=self.repository,  # type: ignore[arg-type]
            pool_lock=self.lock,
            subscribers=subscribers,
            history=_History(),
            enablement_log=_EnablementLog(),  # type: ignore[arg-type]
            clock=_Clock(),
            commit=_Commit(self.events),
        )


# ----------------------------------------------------------------- lock set and order


async def test_archive_locks_every_subscribers_pool_in_ascending_pool_id_order() -> None:
    # Handed back out of order on purpose: the order is the use case's to impose.
    harness = Archiving(
        FakeSubscribers([_pool(9, USER_C), _pool(3, USER_B), author_pool(_strategy(), 5)])
    )

    await harness.use_case.archive(STRATEGY_ID)

    assert [user for user, *_ in harness.lock.acquired] == [USER_B, OWNER_ID, USER_C]


async def test_delete_locks_every_subscribers_pool_in_ascending_pool_id_order() -> None:
    harness = Deleting(
        FakeSubscribers([_pool(9, USER_C), _pool(3, USER_B), author_pool(_strategy(), 5)])
    )

    await harness.use_case.delete(STRATEGY_ID)

    assert [user for user, *_ in harness.lock.acquired] == [USER_B, OWNER_ID, USER_C]


async def test_a_pool_listed_twice_is_locked_once() -> None:
    harness = Archiving(FakeSubscribers([_pool(4, USER_B), _pool(4, USER_B)]))

    await harness.use_case.archive(STRATEGY_ID)

    assert [user for user, *_ in harness.lock.acquired] == [USER_B]


async def test_the_lock_is_the_pools_own_market_not_the_strategys() -> None:
    other_market = ("pionex", "spot", "USDT")
    harness = Archiving(FakeSubscribers([_pool(4, USER_B, other_market)]))

    await harness.use_case.archive(STRATEGY_ID)

    assert harness.lock.acquired == [(USER_B, *other_market)]


async def test_every_pool_lock_comes_before_the_row_lock_and_the_set_is_read_before_both() -> None:
    harness = Archiving(FakeSubscribers([_pool(1, OWNER_ID), _pool(2, USER_B)]))

    await harness.use_case.archive(STRATEGY_ID)

    assert harness.events == [
        "get_by_id",
        "live_pools",
        "pool_lock",
        "pool_lock",
        "get_by_id_for_update",
        "live_pools",  # re-read under the locks
        "update",
        "end_all",
        "commit",
    ]


async def test_delete_takes_every_pool_lock_before_the_row_lock() -> None:
    harness = Deleting(FakeSubscribers([_pool(1, OWNER_ID), _pool(2, USER_B)]))

    await harness.use_case.delete(STRATEGY_ID)

    assert harness.events == [
        "get_by_id",
        "live_pools",
        "pool_lock",
        "pool_lock",
        "get_by_id_for_update",
        "live_pools",
        "delete",
        "commit",
    ]


async def test_a_strategy_nobody_subscribes_to_takes_no_pool_lock_and_still_archives() -> None:
    harness = Archiving(FakeSubscribers([]))

    result = await harness.use_case.archive(STRATEGY_ID)

    assert harness.lock.acquired == []
    assert result.strategy.archived_at == NOW


# ------------------------------------------------- a subscriber joins between read and lock


async def test_a_subscriber_who_joined_after_the_first_read_refuses_the_archive() -> None:
    harness = Archiving(
        FakeSubscribers([_pool(1, OWNER_ID)], [_pool(1, OWNER_ID), _pool(2, USER_B)])
    )

    with pytest.raises(SubscribersChanged):
        await harness.use_case.archive(STRATEGY_ID)

    assert harness.repository.updated == []
    assert harness.subscribers.ended_at == []
    assert "commit" not in harness.events


async def test_a_subscriber_who_joined_after_the_first_read_refuses_the_delete() -> None:
    harness = Deleting(
        FakeSubscribers([_pool(1, OWNER_ID)], [_pool(1, OWNER_ID), _pool(2, USER_B)])
    )

    with pytest.raises(SubscribersChanged):
        await harness.use_case.delete(STRATEGY_ID)

    assert harness.repository.deleted == []
    assert "commit" not in harness.events


async def test_the_refusal_names_the_strategy_and_logs_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = Archiving(
        FakeSubscribers([_pool(1, OWNER_ID)], [_pool(1, OWNER_ID), _pool(2, USER_B)])
    )

    with caplog.at_level(logging.WARNING, logger=LOCKS_LOGGER), pytest.raises(SubscribersChanged):
        await harness.use_case.archive(STRATEGY_ID)

    records = [r for r in caplog.records if r.name == LOCKS_LOGGER]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert str(STRATEGY_ID) in records[0].getMessage()


async def test_a_subscriber_who_left_after_the_first_read_does_not_refuse() -> None:
    harness = Archiving(
        FakeSubscribers([_pool(1, OWNER_ID), _pool(2, USER_B)], [_pool(1, OWNER_ID)])
    )

    result = await harness.use_case.archive(STRATEGY_ID)

    assert result.already_archived is False


# --------------------------------------------------------------- open allocations refuse


async def test_a_non_author_holder_refuses_and_is_named_by_id_prefix_only() -> None:
    exposure = StrategyExposure(frozenset({"STXUSDT"}), (UUID(int=7),), (), ())
    harness = Archiving(
        FakeSubscribers([_pool(1, OWNER_ID), _pool(2, USER_B)], holders=[USER_B]),
        exposure=exposure,
    )

    with pytest.raises(OpenPosition) as refused:
        await harness.use_case.archive(STRATEGY_ID)

    message = str(refused.value)
    assert str(STRATEGY_ID) in message
    assert str(USER_B)[:8] in message
    assert str(USER_B) not in message
    assert refused.value.exposure == exposure
    # Nothing was written: no archive, no subscription ended, no commit.
    assert harness.repository.updated == []
    assert harness.subscribers.ended_at == []
    assert "commit" not in harness.events


async def test_the_authors_holding_keeps_the_existing_refusal() -> None:
    exposure = StrategyExposure(frozenset({"STXUSDT"}), (UUID(int=7),), (), ())
    harness = Archiving(
        FakeSubscribers([_pool(1, OWNER_ID)], holders=[OWNER_ID]), exposure=exposure
    )

    with pytest.raises(OpenPosition) as refused:
        await harness.use_case.archive(STRATEGY_ID)

    assert "still holds exposure" in str(refused.value)
    assert "author" in str(refused.value)
    assert str(OWNER_ID)[:8] not in str(refused.value)


async def test_the_holders_are_asked_of_the_subscribers_read_under_the_locks() -> None:
    exposure = StrategyExposure(frozenset(), (), (UUID(int=7),), ())
    subscribers = FakeSubscribers([_pool(1, OWNER_ID), _pool(2, USER_B)], holders=[USER_B])
    harness = Archiving(subscribers, exposure=exposure)

    with pytest.raises(OpenPosition):
        await harness.use_case.archive(STRATEGY_ID)

    assert subscribers.holders_asked == [[OWNER_ID, USER_B]]


async def test_a_refusal_for_exposure_nobody_holds_still_refuses() -> None:
    """An in-flight attempt belongs to no subscriber the holder read can name; the
    archive still refuses, saying so."""
    exposure = StrategyExposure(frozenset(), (), (), (UUID(int=9),))
    harness = Archiving(FakeSubscribers([_pool(1, OWNER_ID)]), exposure=exposure)

    with pytest.raises(OpenPosition):
        await harness.use_case.archive(STRATEGY_ID)


async def test_a_still_enabled_strategy_ends_no_subscription() -> None:
    harness = Archiving(FakeSubscribers([_pool(1, OWNER_ID)]), strategy=_strategy(enabled=True))

    with pytest.raises(StillEnabled):
        await harness.use_case.archive(STRATEGY_ID)

    assert harness.subscribers.ended_at == []


# ------------------------------------------------------------- ending the subscriptions


async def test_archiving_ends_every_subscription_in_the_archive_transaction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    subscribers = FakeSubscribers([_pool(1, OWNER_ID), _pool(2, USER_B)], ended=2)
    harness = Archiving(subscribers)

    with caplog.at_level(logging.INFO, logger=ARCHIVE_LOGGER):
        await harness.use_case.archive(STRATEGY_ID)

    assert subscribers.ended_at == [NOW]
    assert harness.events.index("end_all") < harness.events.index("commit")
    info = [r for r in caplog.records if r.name == ARCHIVE_LOGGER and r.levelno == logging.INFO]
    assert len(info) == 1
    assert str(STRATEGY_ID) in info[0].getMessage()
    assert "subscriptions_ended=2" in info[0].getMessage()


async def test_replaying_an_archive_ends_what_is_still_live_and_keeps_the_archived_at() -> None:
    earlier = datetime(2026, 10, 1, tzinfo=UTC)
    subscribers = FakeSubscribers([_pool(1, OWNER_ID)], ended=1)
    harness = Archiving(subscribers, strategy=replace(_strategy(), archived_at=earlier))

    result = await harness.use_case.archive(STRATEGY_ID)

    assert result.already_archived is True
    assert result.strategy.archived_at == earlier
    assert subscribers.ended_at == [NOW]
    assert harness.repository.updated == []

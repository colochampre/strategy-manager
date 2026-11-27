"""Fakes of ``StrategySubscribersPort`` for the archive and delete unit tests."""

from collections.abc import Sequence
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from strategy_manager.strategies.application.ports import StrategyExposure, SubscriberPool
from strategy_manager.strategies.domain.strategy import Strategy


def author_pool(strategy: Strategy, pool_id: int = 1) -> SubscriberPool:
    """The author's own pool on the strategy's market: what a strategy that only
    its author subscribes to has."""
    policy = strategy.policy
    return SubscriberPool(
        pool_id=pool_id,
        user_id=strategy.author_id,
        pool=(
            policy.exchange.value,
            policy.venue.value,
            policy.settlement_currency.value,
        ),
    )


class RecordingPoolLock:
    """``PoolLockPort`` that only records, so a unit test reads which pools a use
    case locked and in what order. What a lock serializes is proven on real
    PostgreSQL."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.acquired: list[tuple[UUID, str, str, str]] = []
        self._events = events

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None:
        if self._events is not None:
            self._events.append("pool_lock")
        self.acquired.append((user_id, exchange, venue, settlement_currency))


class FixedExposure:
    """``StrategyExposurePort`` that answers one exposure, flat by default, and
    counts how often it was asked."""

    def __init__(self, answer: StrategyExposure | None = None) -> None:
        self.answer = answer or StrategyExposure(frozenset(), (), (), ())
        self.asked = 0

    async def exposure(self, strategy_id: UUID, pool: tuple[str, str, str]) -> StrategyExposure:
        self.asked += 1
        return self.answer


class DisableGuard(TypedDict):
    """The three keyword arguments ``UpdateStrategy`` takes for the disable guard."""

    pool_lock: RecordingPoolLock
    subscribers: "FakeSubscribers"
    exposure: FixedExposure


def disable_guard(strategy: Strategy, answer: StrategyExposure | None = None) -> DisableGuard:
    """A guard for a strategy only its author subscribes to, flat unless told."""
    return {
        "pool_lock": RecordingPoolLock(),
        "subscribers": FakeSubscribers.sole_author(strategy),
        "exposure": FixedExposure(answer),
    }


class FakeSubscribers:
    """``live_pools`` answers the next of ``reads`` each call (the last one
    repeats), so a test can make the set GROW between the read before the locks
    and the read under them. ``events`` is optional: a test that does not care
    about the order of reads leaves it out."""

    def __init__(
        self,
        *reads: Sequence[SubscriberPool],
        holders: Sequence[UUID] = (),
        events: list[str] | None = None,
        ended: int = 0,
        lowered: int = 0,
    ) -> None:
        self._reads = [list(read) for read in reads]
        self._holders = list(holders)
        self._events = events
        self._ended = ended
        self._lowered = lowered
        self.reads = 0
        self.ended_at: list[datetime] = []
        self.holders_asked: list[list[UUID]] = []
        self.lowered: list[tuple[UUID, int, datetime]] = []

    @classmethod
    def sole_author(cls, strategy: Strategy, **kwargs: object) -> "FakeSubscribers":
        return cls([author_pool(strategy)], **kwargs)  # type: ignore[arg-type]

    async def live_pools(self, strategy_id: UUID) -> list[SubscriberPool]:
        if self._events is not None:
            self._events.append("live_pools")
        read = self._reads[min(self.reads, len(self._reads) - 1)]
        self.reads += 1
        return list(read)

    async def holders(
        self, strategy_id: UUID, subscribers: Sequence[SubscriberPool]
    ) -> list[UUID]:
        self.holders_asked.append([subscriber.user_id for subscriber in subscribers])
        return list(self._holders)

    async def end_all(self, strategy_id: UUID, now: datetime) -> int:
        if self._events is not None:
            self._events.append("end_all")
        self.ended_at.append(now)
        return self._ended

    async def lower_above(self, strategy_id: UUID, cap: int, now: datetime) -> int:
        if self._events is not None:
            self._events.append("lower_above")
        self.lowered.append((strategy_id, cap, now))
        return self._lowered

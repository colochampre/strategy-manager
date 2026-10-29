"""Fakes of ``StrategySubscribersPort`` for the archive and delete unit tests."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from strategy_manager.strategies.application.ports import SubscriberPool
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
    ) -> None:
        self._reads = [list(read) for read in reads]
        self._holders = list(holders)
        self._events = events
        self._ended = ended
        self.reads = 0
        self.ended_at: list[datetime] = []
        self.holders_asked: list[list[UUID]] = []

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

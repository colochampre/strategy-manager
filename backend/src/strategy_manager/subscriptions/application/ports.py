"""Ports of the subscriptions use cases. Every one is scoped to a user, so a use
case cannot be handed another user's row by mistake (multi-user design AD8)."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.subscriptions.domain.subscription import Subscription

#: ``(exchange, venue, settlement_currency)``: one pool of one user.
Market = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class StrategyMarket:
    """What subscribing needs to know about a strategy: where it trades, and
    whether it still takes subscribers."""

    id: UUID
    market: Market
    archived: bool


class SubscriptionRepositoryPort(Protocol):
    async def insert(self, subscription: Subscription) -> None:
        """Raises ``AlreadySubscribed`` when the user's live subscription to the
        strategy was written first (the partial unique index), a race the
        ``has_live`` read before it cannot close."""
        ...

    async def get(self, user_id: UUID, subscription_id: UUID) -> Subscription | None: ...

    async def get_for_update(self, user_id: UUID, subscription_id: UUID) -> Subscription | None:
        """Same, taking the row lock and re-reading what the database holds now."""
        ...

    async def update(self, subscription: Subscription) -> None: ...

    async def get_live_for_update(
        self, user_id: UUID, strategy_id: UUID
    ) -> Subscription | None:
        """The user's ACTIVE or LEAVING subscription to the strategy, taking the
        row lock and re-reading what the database holds now; ``None`` when the
        user holds none. The partial unique index allows at most one."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[Subscription]: ...

    async def has_live(self, user_id: UUID, strategy_id: UUID) -> bool:
        """Whether the user holds an ACTIVE or LEAVING subscription to the strategy."""
        ...


class StrategyLookupPort(Protocol):
    async def find(self, strategy_id: UUID) -> StrategyMarket | None: ...


class UserPoolPort(Protocol):
    async def pool_id(self, user_id: UUID, market: Market) -> int | None:
        """The id of the user's OWN pool on the market, or ``None``."""
        ...


class OpenAllocationPort(Protocol):
    async def holds_open_allocation(
        self, user_id: UUID, strategy_id: UUID, market: Market
    ) -> bool:
        """Whether this user still has exposure from this strategy on the market:
        a position the ledger holds, or a reservation still holding capital."""
        ...


class PoolLockPort(Protocol):
    """The advisory lock ``AllocateCapital`` takes for this user's pool, derived
    through the same ``LockKey`` code path. Taken before any row lock."""

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None: ...


class CommitPort(Protocol):
    async def commit(self) -> None: ...

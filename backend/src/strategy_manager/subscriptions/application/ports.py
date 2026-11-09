"""Ports of the subscriptions use cases. Every one is scoped to a user, so a use
case cannot be handed another user's row by mistake (multi-user design AD8)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.strategies.domain.invite_code import DeadCode, InviteCode
from strategy_manager.strategies.domain.strategy import Visibility
from strategy_manager.subscriptions.domain.subscription import Subscription

#: ``(exchange, venue, settlement_currency)``: one pool of one user.
Market = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class StrategyMarket:
    """What subscribing and leaving need to know about a strategy: where it trades,
    whether it still takes subscribers, who wrote it (an author cannot leave) and
    whether it is offered to anyone else: public (decision 21) and with an author
    who has a name (tasks.md G.2)."""

    id: UUID
    market: Market
    archived: bool
    author_id: UUID
    visibility: Visibility
    author_named: bool
    # The link's token while LINK (decision 41); ``repr`` never names it.
    share_token: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class HeldSubscription:
    """A user's live subscription and what names its strategy to them. A strategy
    that turned private keeps its subscribers (decision 21) and leaves the public
    list, so this is the one place they can still read what they hold."""

    subscription: Subscription
    strategy_name: str
    author_name: str | None
    authored: bool
    market: Market
    # Whether the strategy is taking signals now (tasks.md L.1).
    strategy_enabled: bool


@dataclass(frozen=True, slots=True)
class LeavingSubscription:
    """A LEAVING subscription and the market its pool lock is keyed by."""

    user_id: UUID
    strategy_id: UUID
    market: Market


class LeavingSubscriptionsPort(Protocol):
    async def leaving(self) -> list[LeavingSubscription]:
        """Every user's LEAVING subscription, read plainly: each is decided again
        under its user's pool lock."""
        ...


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


class InviteCodeCheckPort(Protocol):
    """``CheckInviteCode``: the code ``user_id`` typed, if it is a live code of
    ``strategy_id``; None when it is no code of it, which is counted against them.
    Raises ``InviteCodeNotLive`` or ``TooManyCodeAttempts``. Runs in a transaction of
    its own, so a failure it writes outlives the request's rollback."""

    async def check(self, user_id: UUID, strategy_id: UUID, typed: str) -> InviteCode | None: ...


class InviteCodeSpendPort(Protocol):
    """Spends a live code on the seat it made, in the seat's own transaction."""

    async def spend(
        self,
        strategy_id: UUID,
        code: InviteCode,
        user_id: UUID,
        subscription_id: UUID,
        now: datetime,
    ) -> DeadCode | None:
        """Marks the code redeemed by ``user_id`` with ``subscription_id``, waiting on
        and re-reading its row, and answers None. A code no longer live by then is
        left as it is, and the answer says why."""
        ...


class UserPoolPort(Protocol):
    async def pool_id(self, user_id: UUID, market: Market) -> int | None:
        """The id of the user's OWN pool on the market, or ``None``."""
        ...


class OpenAllocationPort(Protocol):
    async def holds_open_allocation(
        self, user_id: UUID, strategy_id: UUID, market: Market
    ) -> bool:
        """Whether this user still has exposure from this strategy on the market:
        a position the ledger holds, a reservation still holding capital, or an
        opening order still in flight."""
        ...


class PoolLockPort(Protocol):
    """The advisory lock ``AllocateCapital`` takes for this user's pool, derived
    through the same ``LockKey`` code path. Taken before any row lock."""

    async def acquire(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> None: ...


class CommitPort(Protocol):
    async def commit(self) -> None: ...

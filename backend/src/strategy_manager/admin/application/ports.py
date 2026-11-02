"""What the admin's users list reads (tasks.md F.7, decision 8).

A read that crosses users on purpose, so its port holds only what the list shows:
nothing here can carry a balance, a share, a price or a return.

Each method is ONE statement however many users there are.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from strategy_manager.identity.domain.user import User

UserExchange = tuple[UUID, str]
"""``(user_id, exchange)``: one user's account on one exchange."""


@dataclass(frozen=True, slots=True)
class ExchangeCoverage:
    """The pairs with an enabled pool and the pairs with an active key, read at
    one moment."""

    enabled_pools: frozenset[UserExchange]
    active_keys: frozenset[UserExchange]


class UsersSourcePort(Protocol):
    async def users(self) -> Sequence[User]:
        """Everyone, by e-mail."""
        ...

    async def coverage(self) -> ExchangeCoverage: ...

    async def live_subscriptions(self) -> Mapping[UUID, int]:
        """How many ``ACTIVE`` or ``LEAVING`` subscriptions each user holds. A user
        with none is absent."""
        ...

    async def open_allocation_owners(self) -> Sequence[UUID]:
        """One entry per open allocation, naming its user."""
        ...

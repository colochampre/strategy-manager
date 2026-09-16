"""Ports (Protocols) owned by ``strategies``. Consumer declares the port,
provider owns the adapter — ``main.py`` binds them together.
"""

from typing import Protocol
from uuid import UUID

from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.domain.strategy import Strategy


class StrategyRepositoryPort(Protocol):
    """Read-through lookup and explicit-id registration. ``insert`` MUST be
    given a ``Strategy`` whose ``id`` was already set explicitly by the
    caller — this port never generates one (design.md § "strategy_id derives
    from signal_type")."""

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None: ...
    async def insert(self, strategy: Strategy) -> None: ...
    async def list_all(self) -> list[Strategy]: ...

    async def update(self, strategy: Strategy) -> None:
        """Writes the mutable fields of an already-registered strategy.

        ``exchange``, ``venue`` and ``settlement_currency`` are NOT among
        them — see ``UpdateStrategy`` for why moving a strategy between pools
        is not an edit.
        """
        ...


class PoolCatalogPort(Protocol):
    """Whether a capital pool exists and is enabled.

    ``strategies`` has a composite foreign key into ``capital_pools``, so the
    database already refuses a strategy on a pool that does not exist. This
    port is not that guarantee — it is the difference between an integrity
    error nobody can read and a message naming the pool and the pools that
    are available.

    It also catches what the FK cannot: a pool row that exists but is
    DISABLED. The allocation engine reads only enabled pools, so a strategy
    on a disabled one would register happily, accept signals, and fail to
    size any of them.
    """

    async def enabled_pools(self) -> list[tuple[Exchange, Venue, Currency]]: ...


class CommitPort(Protocol):
    """Mirrors the same narrow port every other module declares: any object
    with an async ``commit()`` satisfies it structurally."""

    async def commit(self) -> None: ...

"""Ports (Protocols) owned by ``strategies``. Consumer declares the port,
provider owns the adapter — ``main.py`` binds them together.
"""

from datetime import datetime
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

    async def get_by_id_for_update(self, strategy_id: UUID) -> Strategy | None:
        """Same as ``get_by_id``, but takes a row lock (``SELECT ... FOR
        UPDATE``) for the caller's transaction. ``UpdateStrategy`` is the
        only consumer: two concurrent toggles of the SAME strategy must not
        both read the pre-toggle ``enabled`` value and both append an
        enablement event (design.md § 9; tasks.md 2d.3) — the second
        transaction blocks here until the first commits, then re-reads the
        already-changed value and writes no event of its own.
        """
        ...

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


class EnablementLogPort(Protocol):
    """Appends one OBSERVED event to the append-only enablement log
    (``strategy_enablement_events``, migration 0024). Every event this port
    writes is OBSERVED — BASELINE rows are written exclusively, once, by
    that migration itself, for strategies already enabled at deploy time
    (design.md § 9; spec: strategy-lifecycle § "Enable/Disable Event Log").

    ``occurred_at`` is supplied by the CALLER (from an injected
    ``ClockPort``), not defaulted here or left to the database's ``now()``
    — so a test driving this port with a fixed clock gets a deterministic,
    assertable timestamp instead of one it would have to re-read back.
    """

    async def append(self, strategy_id: UUID, enabled: bool, occurred_at: datetime) -> None: ...

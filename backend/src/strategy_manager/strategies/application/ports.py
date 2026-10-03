"""Ports (Protocols) owned by ``strategies``. Consumer declares the port,
provider owns the adapter — ``main.py`` binds them together.
"""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Protocol
from uuid import UUID

from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.strategies.domain.enablement import EnablementEvent
from strategy_manager.strategies.domain.strategy import Strategy

# ``(exchange, venue, settlement_currency)`` — mirrors
# ``signals.application.ports.PoolKey``/``reconciliation``'s own alias
# exactly, redeclared here rather than imported so ``strategies`` never
# reaches across another module's boundary for a bare type alias (the same
# convention every other consumer of a pool triple already follows).
PoolKey = tuple[str, str, str]


# The history kinds that are reported but never refuse a delete (migration 0028).
_NEVER_BLOCKING = frozenset({"enablement_events"})


class StrategyRepositoryPort(Protocol):
    """Read-through lookup and explicit-id registration. ``insert`` MUST be
    given a ``Strategy`` whose ``id`` was already set explicitly by the
    caller — this port never generates one (design.md § "strategy_id derives
    from signal_type")."""

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None: ...
    async def insert(self, strategy: Strategy) -> None: ...

    async def list_all(self, include_archived: bool = False) -> list[Strategy]:
        """Ordered by name. Excludes archived strategies unless
        ``include_archived=True`` (spec: strategy-lifecycle § "Strategy
        Listing Excludes Archived By Default")."""
        ...

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

    async def delete(self, strategy_id: UUID) -> None:
        """Removes the ``strategies`` row with one ``DELETE`` statement, flushed
        but NOT committed. A foreign key that still points at the row refuses it
        in the database, and the adapter raises ``StrategyStillReferenced``
        carrying the violated constraint's NAME: the application layer never sees
        an ``IntegrityError``. ``DeleteStrategy`` is the only caller, and only
        after it has read an empty ``StrategyHistory`` under both locks."""
        ...


class StrategyStillReferenced(DomainError):
    """The database refused a ``DELETE`` of a strategy because a row still
    references it through a foreign key. Raised by the repository adapter
    (design.md addendum 9x, § B): ``DeleteStrategy`` counted nothing, so the count
    is incomplete and that is a defect, not a user error.

    ``constraint`` is the violated constraint's NAME, ``None`` when the driver
    did not report one."""

    def __init__(self, constraint: str | None) -> None:
        super().__init__(f"a foreign key still references the strategy: {constraint}")
        self.constraint = constraint


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

    async def exists(self, pool: PoolKey) -> bool:
        """Whether ``pool`` is a row of ``capital_pools``, enabled or not.

        Only the read endpoint for available pairs asks: it must refuse a made-up
        pool BEFORE any venue is called, and a disabled pool is still answered
        (the public catalogue needs no key, and an existing strategy on a pool
        disabled later can still have its pairs edited).
        """
        ...


class PairCatalogPort(Protocol):
    """Which pairs a strategy on a capital pool may trade, according to the
    venue itself.

    Returns ``market_key`` forms (``STXUSDT``, never ``STXUSDT.P`` or
    ``STXUSDT_PERP``), the form a strategy stores its allowed pairs in.

    Raises ``PairCatalogNotServed`` when no catalogue source exists for the
    pool's exchange and venue, and ``PairCatalogUnavailable`` when the venue
    cannot be read. It never answers an empty set for either: an empty answer
    would read as "this venue lists nothing", and a stale answer would accept a
    pair on evidence that has expired.
    """

    async def available_pairs(self, pool: PoolKey) -> frozenset[str]: ...


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


class EnablementReaderPort(Protocol):
    """Reads one strategy's enablement events. ``DeleteStrategy`` reads them just
    before the delete, while they still exist, because its INFO line is the only
    record of when the strategy was enabled once migration 0028 deletes them with
    it. Implemented by ``SqlAlchemyEnablementLog``. Read-only."""

    async def list_for(self, strategy_id: UUID) -> list[EnablementEvent]: ...


@dataclass(frozen=True, slots=True)
class StrategyExposure:
    """What ``ArchiveStrategy`` checks before archiving (design.md § 8,
    decision 14's precondition: "disabled AND flat"). Any field non-empty
    means the strategy still holds exposure on its pool, and archiving now
    would make every future signal for it refused (decision 11) while
    nothing could ever close what is still open.

    ``symbols``/``allocations`` come from the ledger: a non-zero net base
    PER ALLOCATION (never one summed net per symbol — the multiplicity
    lesson, design.md § 8, tasks.md 2c.11), merged across every spelling a
    market wears, across EVERY market this strategy has ever touched in
    this pool, not only the ones currently on its ``allowed_pairs`` list —
    decision 15 lets a pair be delisted while a position it opened is still
    live. ``live_reservations`` is PENDING/SUBMITTED with ``terminal_at
    NULL``. ``in_flight_attempts`` is a SUBMITTED execution attempt, opening
    or closing, tied to this strategy through whichever reservation it
    belongs to.
    """

    symbols: frozenset[str]
    allocations: tuple[UUID, ...]
    live_reservations: tuple[UUID, ...]
    in_flight_attempts: tuple[UUID, ...]

    def is_empty(self) -> bool:
        return not (
            self.symbols
            or self.allocations
            or self.live_reservations
            or self.in_flight_attempts
        )


class StrategyExposurePort(Protocol):
    """Implemented by
    ``strategies.infrastructure.exposure_adapter.StrategyExposureAdapter``,
    which composes ledger ``ReadSymbolHoldings``, reservations and
    attempts, following the ``InFlightWorkAdapter`` precedent
    (design.md's component inventory)."""

    async def exposure(self, strategy_id: UUID, pool: PoolKey) -> StrategyExposure: ...


@dataclass(frozen=True, slots=True)
class StrategyHistory:
    """How many rows of each kind reference a strategy (design.md addendum
    9x, § C). ``DeleteStrategy`` deletes only when every count is zero.

    Counts are by strategy id alone, across EVERY capital pool: a strategy
    lives in one pool and cannot be moved, so a row in another pool should
    not exist, and if one does it must still block. Plain integers: nothing
    of ``signals``, ``allocation``, ``execution``, ``ledger`` or
    ``reconciliation`` appears here, so this port stays free of those modules.

    The six kinds are the five foreign keys into ``strategies`` plus the
    execution attempts that reach a strategy through a reservation or a
    signal. ``test_strategy_references_guard`` reads ``pg_constraint`` and
    fails when a migration adds a reference this class does not count.

    **Enablement events are counted but never block** (owner decision 42, Q1;
    migration 0028 deletes them with their strategy). They stay a field so the
    refusal's body keeps its six keys and the delete's INFO line can name how
    many went; ``blocking()`` and ``is_empty()`` leave them out. Before 0028 is
    applied the foreign key still refuses a strategy that has events: the
    database says so, and ``DeleteStrategy`` answers it as ``HAS_HISTORY``.
    """

    signals: int
    reservations: int
    execution_attempts: int
    ledger_entries: int
    booking_proposals: int
    enablement_events: int

    def blocking(self) -> dict[str, int]:
        """The non-zero kinds that refuse a delete, in the fixed order of the
        fields. Never ``enablement_events``."""
        return {
            field.name: count
            for field in fields(self)
            if field.name not in _NEVER_BLOCKING and (count := getattr(self, field.name)) > 0
        }

    def is_empty(self) -> bool:
        return not self.blocking()


class StrategyHistoryPort(Protocol):
    """Implemented by
    ``strategies.infrastructure.history_adapter.StrategyHistoryAdapter``,
    which composes one narrow count per provider repository, following the
    ``StrategyExposurePort`` precedent. Takes no pool: see ``StrategyHistory``.
    Read-only: it takes no lock and writes nothing."""

    async def history(self, strategy_id: UUID) -> StrategyHistory: ...


class PoolLockPort(Protocol):
    """Takes EXACTLY the advisory lock ``AllocateCapital`` takes for this
    pool -- derived through the SAME ``allocation.domain.lock_key.LockKey
    .from_pool_key`` code path, never re-derived by hand (design.md § 8,
    "same key AllocateCapital takes"). A different derivation would compile
    and pass every fake-backed test while silently serializing nothing
    against a concurrent allocation -- proven only against real Postgres,
    by ``test_archive_vs_allocate_concurrency.py``.

    Implemented by ``strategies.infrastructure.pool_lock_adapter
    .PoolLockAdapter``, which wraps ``allocation.infrastructure
    .advisory_lock.PgAdvisoryLockAdapter`` directly rather than
    reimplementing the SQL.
    """

    async def acquire(self, exchange: str, venue: str, settlement_currency: str) -> None: ...

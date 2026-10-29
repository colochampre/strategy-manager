"""Ports (Protocols) and consumer-owned DTOs declared by ``allocation``,
implemented by ``strategies``, ``accounts`` and ``allocation.infrastructure``
itself (design.md § Interfaces / Contracts). The consumer declares the port,
the provider owns the adapter — ``StrategyPolicyPort``/``PoolBalancePort``
were declared in slice 3 so slice 4's ``AllocateCapital`` consumes them
unchanged; ``AdvisoryLockPort``/``ReservationRepositoryPort`` are added here in
slice 4.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus


@dataclass(frozen=True, slots=True)
class StrategyPolicySnapshot:
    """What ``AllocateCapital`` needs to know about a strategy, decoupled
    from the ``strategies`` module's own aggregate — no provider type leaks
    across the module boundary.

    ``archived`` and ``allowed_pairs`` back the two ``signals.application.
    process_signal`` refusals added in unit 2b (design.md § 7-8): the
    allowlist gates the OPENING effect only, and an archived strategy is
    refused whatever its pool. Both default so every pre-existing caller
    that does not care about lifecycle (``AllocateCapital``'s own in-lock
    re-check, unit 2c) keeps constructing this DTO unchanged. ``name`` is
    carried only for the archived-strategy WARNING text (design.md § 8),
    which names the strategy for the owner rather than just its id.

    ``author_id`` is the strategy's author (multi-user design AD2). Until
    subscriptions exist (PR C), a signal is allocated in its author's pool: the
    balance, the pool flag and the sizing are read for that user (B.5).
    """

    strategy_id: UUID
    enabled: bool
    fill_mode: str  # 'SKIP' | 'PARTIAL'
    exchange: str
    venue: str
    settlement_currency: str
    author_id: UUID
    name: str = ""
    archived: bool = False
    allowed_pairs: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PoolBalance:
    """What ``AllocateCapital`` needs to know about a pool's current state.

    ``total`` is the sizing base for ``allocation_percent``; ``available``
    is the ceiling on what may be granted. Mixing them up either compounds
    sizes as positions open or grants capital that is already committed.
    """

    total: Decimal
    available: Decimal
    min_order_size: Decimal


@dataclass(frozen=True, slots=True)
class SizingSnapshot:
    """The last balance a pool was synced to, as a DISPLAY needs it: the TOTAL
    (the base a share is sized from), when the exchange reported it, and whether
    that is older than the allocator's own limit. There is no ``available`` here,
    because nothing a preview shows may be computed from it."""

    total: Decimal
    observed_at: datetime
    stale: bool


@dataclass(frozen=True, slots=True)
class PoolSizing:
    """What ``PreviewShare`` needs to know about one pool: its minimum order and,
    when something has synced it, its snapshot. ``snapshot`` is ``None`` for a pool
    nothing has synced, which is not a balance of zero."""

    min_order_size: Decimal
    snapshot: SizingSnapshot | None


class StrategyPolicyPort(Protocol):
    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot: ...


class PoolSizingPort(Protocol):
    """Reads a pool's minimum order and its latest snapshot FOR DISPLAY (the share
    preview). Read-only by its shape -- it has no write -- and MUST take no lock.

    It is not ``PoolBalancePort``: that one refuses a stale snapshot, which is right
    for sizing a trade and wrong for a figure that must be shown and marked stale.
    A pool with no row answers ``None``; a pool with a row and no snapshot answers
    a ``PoolSizing`` whose ``snapshot`` is ``None``.

    The pool is ``user_id``'s (multi-user design AD8)."""

    async def read(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> PoolSizing | None: ...


class PoolBalancePort(Protocol):
    """Implementations MUST be local (DB or in-memory). A synchronous remote
    call here would run inside the advisory lock (design.md § Interfaces).

    The pool is ``user_id``'s (multi-user design AD8): another user's pool on the
    same market is never read."""

    async def read(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> PoolBalance: ...


class PoolStatusPort(Protocol):
    """Reads whether a capital pool has been DISABLED, from committed state.

    ``AllocateCapital`` calls it inside the advisory lock, right where it
    re-reads the strategy policy: ``DeleteCredential`` disables the pool under
    that same lock, so an allocation that waited for it must observe the
    committed flag rather than a value read before the wait.

    MUST be a plain read with no row lock: a waiting allocation must not hold
    a lock the delete needs (lock order: advisory first, then row locks).
    A pool with no row is NOT reported disabled -- that misconfiguration keeps
    failing loudly through ``PoolBalancePort`` as it always has.

    The pool is ``user_id``'s (multi-user design AD8)."""

    async def is_disabled(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> bool: ...


class AdvisoryLockPort(Protocol):
    """MUST run on the same session/connection as the reservation write, MUST
    be inside an open transaction, and MUST be released only by that
    transaction's commit or rollback."""

    async def acquire(self, key: LockKey) -> None: ...


class ReservationRepositoryPort(Protocol):
    """Every method names the user whose reservations it reads or writes
    (multi-user design AD8): another user's reservation on the same market is
    never returned, counted or changed, and ``insert`` writes the reservation
    as that user's, in that user's pool on its market."""

    async def find_by_signal_id(self, user_id: UUID, signal_id: UUID) -> Reservation | None: ...

    async def sum_active(
        self,
        user_id: UUID,
        exchange: str,
        venue: str,
        settlement_currency: str,
        now: datetime,
    ) -> Decimal: ...

    async def insert(self, user_id: UUID, reservation: Reservation) -> None: ...

    async def mark(
        self, user_id: UUID, reservation_id: UUID, status: ReservationStatus, at: datetime
    ) -> None: ...


class ReservationSweepPort(Protocol):
    """Batch expiry for the sweeper (design.md § Transaction Boundaries,
    TXN-C). Separate from ``ReservationRepositoryPort`` because the sweeper
    needs none of the per-signal reads and must not be handed the ability to
    insert — a set-based UPDATE is its whole vocabulary.

    Global by design: it sweeps every user's reservations (multi-user design
    AD8), since expiry is a property of the row and the worker's housekeeping
    has no user context."""

    async def expire_due(self, now: datetime, limit: int) -> int:
        """Terminates up to ``limit`` reservations whose ``expires_at`` has
        passed and whose status still holds capital. Returns how many changed.
        MUST be idempotent: a second call over the same rows changes nothing."""
        ...


class CommitPort(Protocol):
    """The minimal capability ``AllocateCapital`` needs to finalize TXN-A.
    Deliberately narrow, mirroring ``signals.application.ports.CommitPort``,
    so any object with an async ``commit()`` (including a raw ``AsyncSession``)
    satisfies it structurally."""

    async def commit(self) -> None: ...

class SkipRecorderPort(Protocol):
    """Records, on the caller's own session, that ``AllocateCapital`` set a
    delivery aside (decision 25, design.md "Addendum: signal outcomes" § C,
    row 8; per delivery since tasks.md C.7). Declared here, consumer-side, so
    ``allocation`` never imports ``signals``;
    ``signals.infrastructure.skip_recorder.SignalSkipRecorder`` adapts it onto
    ``DeliveryOutcomePort``.

    Like ``SignalOutcomePort.record`` it stages the write and NEVER commits:
    ``AllocateCapital`` calls it immediately before the commit that makes the
    skip durable. ``reason`` is the existing ``skip_reason`` value and
    ``detail`` the human message already logged for the skip."""

    async def record_skip(self, delivery_id: UUID, reason: str, detail: str) -> None: ...

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
    across the module boundary."""

    strategy_id: UUID
    enabled: bool
    fill_mode: str  # 'SKIP' | 'PARTIAL'
    venue: str
    settlement_currency: str
    allocation_percent: Decimal  # 0 < value <= 100 (tasks.md 7.6)


@dataclass(frozen=True, slots=True)
class PoolBalance:
    """What ``AllocateCapital`` needs to know about a pool's current state."""

    balance: Decimal
    min_order_size: Decimal


class StrategyPolicyPort(Protocol):
    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot: ...


class PoolBalancePort(Protocol):
    """Implementations MUST be local (DB or in-memory). A synchronous remote
    call here would run inside the advisory lock (design.md § Interfaces)."""

    async def read(self, venue: str, settlement_currency: str) -> PoolBalance: ...


class AdvisoryLockPort(Protocol):
    """MUST run on the same session/connection as the reservation write, MUST
    be inside an open transaction, and MUST be released only by that
    transaction's commit or rollback."""

    async def acquire(self, key: LockKey) -> None: ...


class ReservationRepositoryPort(Protocol):
    async def find_by_signal_id(self, signal_id: UUID) -> Reservation | None: ...

    async def sum_active(
        self, venue: str, settlement_currency: str, now: datetime
    ) -> Decimal: ...

    async def insert(self, reservation: Reservation) -> None: ...

    async def mark(
        self, reservation_id: UUID, status: ReservationStatus, at: datetime
    ) -> None: ...


class ReservationSweepPort(Protocol):
    """Batch expiry for the sweeper (design.md § Transaction Boundaries,
    TXN-C). Separate from ``ReservationRepositoryPort`` because the sweeper
    needs none of the per-signal reads and must not be handed the ability to
    insert — a set-based UPDATE is its whole vocabulary."""

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

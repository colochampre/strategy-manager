"""Ports (Protocols) and consumer-owned DTOs declared by ``allocation``,
implemented by ``strategies`` and ``accounts`` (design.md § Interfaces /
Contracts). The consumer declares the port, the provider owns the adapter —
declared here in slice 3 so slice 4's ``AllocateCapital`` consumes them
unchanged.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID


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

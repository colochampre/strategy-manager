"""Ports (Protocols) owned by ``strategies``. Consumer declares the port,
provider owns the adapter — ``main.py`` binds them together.
"""

from typing import Protocol
from uuid import UUID

from strategy_manager.strategies.domain.strategy import Strategy


class StrategyRepositoryPort(Protocol):
    """Read-through lookup and explicit-id registration. ``insert`` MUST be
    given a ``Strategy`` whose ``id`` was already set explicitly by the
    caller — this port never generates one (design.md § "strategy_id derives
    from signal_type")."""

    async def get_by_id(self, strategy_id: UUID) -> Strategy | None: ...
    async def insert(self, strategy: Strategy) -> None: ...

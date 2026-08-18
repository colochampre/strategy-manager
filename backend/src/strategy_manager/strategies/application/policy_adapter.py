"""Implements ``allocation.application.StrategyPolicyPort`` by mapping the
``strategies`` module's own aggregate to allocation's consumer-owned DTO —
no ``allocation`` type leaks back into ``strategies`` (design.md § Interfaces
/ Contracts).
"""

from uuid import UUID

from strategy_manager.allocation.application.ports import StrategyPolicySnapshot
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import StrategyRepositoryPort


class UnknownStrategyError(DomainError):
    """Raised when a signal references a ``strategy_id`` with no matching row."""


class StrategyPolicyAdapter:
    """Implements ``allocation.application.StrategyPolicyPort``."""

    def __init__(self, repository: StrategyRepositoryPort) -> None:
        self._repository = repository

    async def policy_for(self, strategy_id: UUID) -> StrategyPolicySnapshot:
        strategy = await self._repository.get_by_id(strategy_id)
        if strategy is None:
            raise UnknownStrategyError(f"no strategy registered for id {strategy_id}")

        return StrategyPolicySnapshot(
            strategy_id=strategy.id,
            enabled=strategy.enabled,
            fill_mode=strategy.policy.fill_mode.value,
            venue=strategy.policy.venue.value,
            settlement_currency=strategy.policy.settlement_currency.value,
            allocation_percent=strategy.policy.allocation_percent.value,
        )

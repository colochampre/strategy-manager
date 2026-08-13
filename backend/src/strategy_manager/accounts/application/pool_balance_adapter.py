"""Implements ``allocation.application.PoolBalancePort`` by combining a
startup-loaded ``PoolConfig`` snapshot (``capital_pools`` is the single
source of truth, loaded once via ``CapitalPoolRepository`` in ``main.py``'s
lifespan) with a live ``BalanceSourcePort`` read.
"""

from collections.abc import Mapping

from strategy_manager.accounts.application.ports import BalanceSourcePort
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.application.ports import PoolBalance
from strategy_manager.shared.domain.errors import InvariantViolation


class PoolBalanceAdapter:
    """Implements ``allocation.application.PoolBalancePort``."""

    def __init__(
        self,
        pools: Mapping[tuple[str, str], PoolConfig],
        balance_source: BalanceSourcePort,
    ) -> None:
        self._pools = pools
        self._balance_source = balance_source

    async def read(self, venue: str, settlement_currency: str) -> PoolBalance:
        pool = self._pools.get((venue, settlement_currency))
        if pool is None:
            raise InvariantViolation(
                f"no configured pool for ({venue}, {settlement_currency})"
            )

        balance = await self._balance_source.read_balance(venue, settlement_currency)
        return PoolBalance(balance=balance, min_order_size=pool.min_order_size)

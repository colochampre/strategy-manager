"""Implements ``allocation.application.PoolBalancePort`` by combining the
enabled ``PoolConfig`` map with a live ``BalanceSourcePort`` read.

``capital_pools`` is the single source of truth. The worker hands in a map it
refreshes on every ``balance.sync`` cycle (``main._PoolSet``), so a pool
enabled or disabled while it runs is seen within one sync interval. A pool
missing from the map raises rather than degrading: an opening signal on a
disabled pool fails loudly instead of allocating against unconfigured capital.

The map is keyed by ``(user_id, market)`` (multi-user design AD8): two users may
each hold a pool on one market, with different minimums and different money, so
the pool read is always the one of the ``user_id`` asked about.
"""

from collections.abc import Mapping
from uuid import UUID

from strategy_manager.accounts.application.ports import BalanceSourcePort, PoolKey
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.allocation.application.ports import PoolBalance
from strategy_manager.shared.domain.errors import InvariantViolation


class PoolBalanceAdapter:
    """Implements ``allocation.application.PoolBalancePort``."""

    def __init__(
        self,
        pools: Mapping[tuple[UUID, PoolKey], PoolConfig],
        balance_source: BalanceSourcePort,
    ) -> None:
        self._pools = pools
        self._balance_source = balance_source

    async def read(
        self, user_id: UUID, exchange: str, venue: str, settlement_currency: str
    ) -> PoolBalance:
        pool = self._pools.get((user_id, (exchange, venue, settlement_currency)))
        if pool is None:
            raise InvariantViolation(
                f"no configured pool for ({exchange}, {venue}, {settlement_currency}) "
                f"of user {str(user_id)[:8]}"
            )

        funds = await self._balance_source.read_balance(
            user_id, exchange, venue, settlement_currency
        )
        return PoolBalance(
            total=funds.total,
            available=funds.available,
            min_order_size=pool.min_order_size,
        )

"""``PreviewShare``: what a share of a pool's TOTAL balance would ask for, read
for display (design.md, unit 12f addendum, sections C2 and H; spec: admin-api
"The Share Preview Route Serves The Amount A Share Asks For").

One read of ``PoolSizingPort``, then the pure functions of
``allocation/domain/share_preview.py``. Deliberately absent: a lock, a commit, a
write, a clock and any exchange. The real allocation still reads the balance,
decides and reserves together under the pool's advisory lock; this is an estimate
taken outside that transaction, and it says so by not taking part in it.

It is not ``AllocateCapital`` and does not use ``PoolBalancePort``: that port
refuses a stale snapshot, which is right for sizing a trade and wrong for a figure
that must be shown, marked stale.
"""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.allocation.application.allocate_capital import UnknownPoolError
from strategy_manager.allocation.application.ports import PoolSizingPort, SizingSnapshot
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.share_preview import (
    ShareAmount,
    share_amount,
    step_amounts,
)


@dataclass(frozen=True, slots=True)
class SharePreview:
    """``balance``, ``exact`` and ``steps`` are present together or absent together:
    with no snapshot there is no amount, never a zero."""

    pool: PoolKey
    pool_minimum: Decimal
    balance: SizingSnapshot | None
    exact: ShareAmount | None
    steps: tuple[ShareAmount, ...]


class PreviewShare:
    def __init__(self, sizing: PoolSizingPort) -> None:
        self._sizing = sizing

    async def preview(self, pool: PoolKey, share: Decimal) -> SharePreview:
        """``share`` is the percentage to preview as ``exact``: the strategy's stored
        share, or the one the caller asked about. The hundred steps do not depend on it.

        Raises ``UnknownPoolError`` for a pool the port has no row for: a strategy
        cannot be registered on one, so it is a fault in stored data, not an answer.
        """

        sizing = await self._sizing.read(
            pool.exchange.value, pool.venue.value, pool.settlement_currency.value
        )
        if sizing is None:
            raise UnknownPoolError(
                f"pool ({pool.exchange.value}, {pool.venue.value}, "
                f"{pool.settlement_currency.value}) has no capital_pools row"
            )

        snapshot = sizing.snapshot
        if snapshot is None:
            return SharePreview(
                pool=pool,
                pool_minimum=sizing.min_order_size,
                balance=None,
                exact=None,
                steps=(),
            )
        return SharePreview(
            pool=pool,
            pool_minimum=sizing.min_order_size,
            balance=snapshot,
            exact=share_amount(snapshot.total, share, sizing.min_order_size),
            steps=step_amounts(snapshot.total, sizing.min_order_size),
        )

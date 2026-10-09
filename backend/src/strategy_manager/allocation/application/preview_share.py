"""STUB (12f.9.10, RED commit): answers a preview with no balance, no exact amount
and no steps, and reads nothing."""

from dataclasses import dataclass
from decimal import Decimal

from strategy_manager.allocation.application.ports import PoolSizingPort, SizingSnapshot
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.share_preview import ShareAmount


@dataclass(frozen=True, slots=True)
class SharePreview:
    pool: PoolKey
    pool_minimum: Decimal
    balance: SizingSnapshot | None
    exact: ShareAmount | None
    steps: tuple[ShareAmount, ...]


class PreviewShare:
    def __init__(self, sizing: PoolSizingPort) -> None:
        self._sizing = sizing

    async def preview(self, pool: PoolKey, share: Decimal) -> SharePreview:
        return SharePreview(
            pool=pool, pool_minimum=Decimal(0), balance=None, exact=None, steps=()
        )

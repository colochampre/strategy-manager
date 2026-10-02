"""``ReadAvailablePairs``: the pairs a pool's venue lists, for the selector.

Read-only. It places nothing, writes nothing and needs no credential, and it
does not consult ``DRY_RUN``: the catalogue is public data and the validation it
feeds has to be true before the system goes live, not after.

**The pool is checked before the catalogue.** A path value that names no
``capital_pools`` row raises ``UnknownPool`` without a venue call or a cache
entry, so a made-up URL can neither reach a venue nor grow the cache. A DISABLED
pool is still answered: the list is public, and a strategy on a pool disabled
later can still have its pairs edited.

``PairCatalogNotServed`` and ``PairCatalogUnavailable`` pass through untouched.
There is no empty list standing in for either: an empty answer would read as
"this venue lists nothing".
"""

from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import (
    PairCatalogPort,
    PoolCatalogPort,
    PoolKey,
)


class UnknownPool(DomainError):
    """The pool is not a row of ``capital_pools``."""


class ReadAvailablePairs:
    def __init__(self, pools: PoolCatalogPort, pairs: PairCatalogPort) -> None:
        self._pools = pools
        self._pairs = pairs

    async def execute(self, pool: PoolKey) -> list[str]:
        """``market_key`` forms, sorted: the form a save accepts back."""
        if not await self._pools.exists(pool):
            raise UnknownPool(f"no such pool: {pool[0]}/{pool[1]}/{pool[2]}")
        return sorted(await self._pairs.available_pairs(pool))

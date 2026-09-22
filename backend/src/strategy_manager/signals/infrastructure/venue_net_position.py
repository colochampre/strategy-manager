"""``VenueNetPositionAdapter``: implements
``signals.application.ports.VenueNetPositionPort`` -- the Existing-Position
Guard's divergent-branch venue read (spec: capital-allocation § Orphan
Classification; design.md § S4).

Reuses ``reconciliation.application.ports.VenuePositionReaderRegistryPort``
exactly: the same routing-by-``(exchange, venue)`` rule
``ExchangeRegistryPort`` already enforces for orders, applied here to a read.
The registry's OWN readers are the composition root's concern (main.py) --
under DRY_RUN they are ``FakeVenuePositionReader``s wrapping
``FakeVenueBook``; live, they are lazily-built wrappers around
``BybitVenuePositionReader``/``BinanceVenuePositionReader`` so a missing or
undecryptable credential on ONE exchange never costs a signal on the OTHER,
mirroring the correction ``RefreshPoolBalance``'s own reader already needed
(design.md § S3 correction, 2026-09-21).

ANY failure -- an unserved pool, a transport error, or this read's own
3-second timeout -- degrades to ``None`` rather than raising: a divergent
holding whose venue cannot be read is exactly the AMBIGUOUS case, never a
crashed job. Mirrors ``RefreshPoolBalance.refresh``'s own ``except
Exception`` boundary for the same reason.
"""

import asyncio
import logging
from decimal import Decimal

from strategy_manager.execution.domain.market_symbol import market_spellings
from strategy_manager.reconciliation.application.ports import (
    VenuePositionReaderRegistryPort,
)
from strategy_manager.signals.application.ports import PoolKey

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


class VenueNetPositionAdapter:
    def __init__(
        self,
        registry: VenuePositionReaderRegistryPort,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def net_position(self, pool: PoolKey, symbol: str) -> Decimal | None:
        exchange, venue, _ = pool
        try:
            async with asyncio.timeout(self._timeout_seconds):
                reader = self._registry.for_pool(exchange, venue)
                positions = await reader.open_positions(pool)
        except Exception as exc:  # noqa: BLE001 - a timeout, an unserved
            # pool and a transport failure all degrade identically here: the
            # caller must never see an exception out of this read, only
            # AMBIGUOUS (``None``).
            logger.warning(
                "venue net position read failed for pool %s on %s: %s",
                pool,
                symbol,
                exc,
            )
            return None

        spellings = market_spellings(symbol)
        return sum(
            (position.net_base for position in positions if position.symbol.upper() in spellings),
            start=_ZERO,
        )

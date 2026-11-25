"""The open positions' mark price: the venue's public mark source, behind the
use case's port (RD.3b).

The sources are the ones a simulated fill prices at
(``execution.infrastructure.venue_mark_prices``): public endpoints, no key, so
nothing here signs and no credential is read or logged.
"""

import asyncio
from collections.abc import Mapping
from decimal import Decimal

from strategy_manager.execution.infrastructure.venue_mark_prices import MarkPriceSource


class PublicOpenPositionMarks:
    def __init__(self, sources: Mapping[str, MarkPriceSource], timeout_seconds: float) -> None:
        self._sources = dict(sources)
        self._timeout_seconds = timeout_seconds

    async def mark_price(self, exchange: str, market: str) -> Decimal | None:
        """The mark of ``market`` on ``exchange``, ``None`` for an exchange with no
        public source. A read that fails, or outlasts ``timeout_seconds`` as a
        whole (the HTTP client's own timeout is per phase), raises."""
        source = self._sources.get(exchange)
        if source is None:
            return None
        async with asyncio.timeout(self._timeout_seconds):
            return await source.mark_price(market)


class NoOpenPositionMarks:
    """A process that was given no mark source: every mark is unknown."""

    async def mark_price(self, exchange: str, market: str) -> Decimal | None:
        return None

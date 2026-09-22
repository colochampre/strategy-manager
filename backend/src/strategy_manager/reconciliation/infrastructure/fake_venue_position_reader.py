"""Implements ``VenuePositionReaderPort`` over ``FakeVenueBook`` -- wired
only under DRY_RUN (design.md § S4), so the REAL branch of orphan
classification is reachable in rehearsal exactly as it is live, without a
real credential.
"""

from strategy_manager.execution.infrastructure.fake_venue_book import FakeVenueBook
from strategy_manager.reconciliation.application.ports import PoolKey
from strategy_manager.reconciliation.domain.positions import VenuePosition


class FakeVenuePositionReader:
    """Implements ``VenuePositionReaderPort`` for one DRY_RUN exchange."""

    def __init__(self, exchange: str, venues: frozenset[str], book: FakeVenueBook) -> None:
        self.exchange = exchange
        self.venues = venues
        self._book = book

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        positions = await self._book.open_positions(pool)
        return [VenuePosition(symbol=market, net_base=net) for market, net in positions]

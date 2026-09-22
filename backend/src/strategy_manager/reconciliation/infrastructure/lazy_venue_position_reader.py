"""``LazyVenuePositionReader``: defers building the real per-exchange venue
position reader -- a decrypted trade-key credential and an open HTTP client
-- until ``open_positions`` is actually called, and builds it AT MOST ONCE
per instance thereafter.

Exists because ``VenueNetPositionAdapter``'s divergent-branch read only ever
needs ONE exchange's reader, for ONE signal, and only when the Existing-
Position Guard actually reaches that branch -- most jobs (every RELEASES
signal, every CONSUMES signal whose holding is not divergent) never call it
at all. Building both exchanges' credentials and clients unconditionally at
job entry, the way constructing ``VenuePositionReaderRegistry`` from already-
built readers would require, is exactly the mistake
``RefreshPoolBalance``'s ``ReaderByExchange`` correction fixed for the
balance refresh (design.md § S3 correction, 2026-09-21) -- replayed here for
the venue-position read, since a missing or undecryptable credential on one
exchange must never cost a signal on the OTHER exchange, or a close on
either, its ability to run.
"""

from collections.abc import Awaitable, Callable

from strategy_manager.reconciliation.application.ports import PoolKey, VenuePositionReaderPort
from strategy_manager.reconciliation.domain.positions import VenuePosition

ReaderFactory = Callable[[], Awaitable[VenuePositionReaderPort]]


class LazyVenuePositionReader:
    """Implements ``VenuePositionReaderPort``, standing in for a real reader
    that does not exist yet."""

    def __init__(self, exchange: str, venues: frozenset[str], factory: ReaderFactory) -> None:
        self.exchange = exchange
        self.venues = venues
        self._factory = factory
        self._built: VenuePositionReaderPort | None = None

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        if self._built is None:
            self._built = await self._factory()
        return await self._built.open_positions(pool)

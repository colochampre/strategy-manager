"""``ReadPublicStrategies``: the public list and a strategy's public page
(tasks.md F.4 and G.8, decisions 28, 30 and 34).

Whether a strategy is listed is the source's to say. This adds what a listing
shows beside its own facts: the record, built from its author's real fills, and
who trades it live. A trade the record cannot read is said in a warning, so a
strategy never quietly shows fewer trades than its author made.

**The brake.** Someone trades live when their subscription is ``ACTIVE`` and
their effective mode is ``LIVE``. The source reads the first half and ``users.mode``;
the brake is process-wide, and under it nobody's effective mode is ``LIVE``, so
the live count is 0 and the capital is absent rather than a sum nobody trades.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from strategy_manager.performance.application.ports import (
    PublicListing,
    PublicStrategiesSourcePort,
)
from strategy_manager.performance.domain.closed_trade import FillGroup
from strategy_manager.performance.domain.public_capital import LiveSeat, public_capital
from strategy_manager.performance.domain.public_record import (
    PublicRecord,
    build_public_record,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PublicStrategy:
    listing: PublicListing
    record: PublicRecord
    live_subscribers: int
    capital: Decimal | None


class ReadPublicStrategies:
    def __init__(self, source: PublicStrategiesSourcePort, *, brake: bool) -> None:
        self._source = source
        self._brake = brake

    async def read_all(self) -> tuple[PublicStrategy, ...]:
        return await self._decorated(await self._source.listings())

    async def read_one(self, strategy_id: UUID, reader_id: UUID) -> PublicStrategy | None:
        listing = await self._source.listing(strategy_id, reader_id)
        if listing is None:
            return None
        [strategy] = await self._decorated((listing,))
        return strategy

    async def _decorated(self, listings: Sequence[PublicListing]) -> tuple[PublicStrategy, ...]:
        if not listings:
            return ()
        ids = [listing.strategy_id for listing in listings]
        fills = await self._source.author_fills(ids)
        seats: Mapping[UUID, Sequence[LiveSeat]] = (
            {} if self._brake else await self._source.live_seats(ids)
        )
        return tuple(
            self._strategy(
                listing,
                fills.get(listing.strategy_id, ()),
                seats.get(listing.strategy_id, ()),
            )
            for listing in listings
        )

    def _strategy(
        self,
        listing: PublicListing,
        fills: Sequence[FillGroup],
        seats: Sequence[LiveSeat],
    ) -> PublicStrategy:
        record = build_public_record(fills)
        if record.unresolved_allocation_ids:
            logger.warning(
                "public strategy %s leaves out of its record %d trade(s) whose symbol "
                "cannot be split against the settlement currency: %s",
                listing.strategy_id,
                len(record.unresolved_allocation_ids),
                ", ".join(str(each) for each in record.unresolved_allocation_ids),
            )
        return PublicStrategy(
            listing=listing,
            record=record,
            live_subscribers=len(seats),
            capital=None if self._brake else public_capital(seats),
        )

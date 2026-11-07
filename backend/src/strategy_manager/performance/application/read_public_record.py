"""``ReadPublicRecord``: a public strategy's record laid out for the page (tasks.md
I.12a, decisions 34 and 40).

Whether the strategy can be read is the source's to say, as for the page itself: on
the public list, or turned private under the reader's own live seat (tasks.md J.1);
any other answers ``None``. The record is built from the
author's real fills only (rehearsal never counts), and a trade the record cannot read
is said in a warning, so a record never quietly shows fewer trades than were made.
It carries no amount: the author's money stays private.
"""

import logging
from uuid import UUID

from strategy_manager.performance.application.ports import PublicStrategiesSourcePort
from strategy_manager.performance.domain.public_record import RecordReport, build_record_report
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)


class ReadPublicRecord:
    def __init__(self, source: PublicStrategiesSourcePort, clock: ClockPort) -> None:
        self._source = source
        self._clock = clock

    async def read(self, strategy_id: UUID, reader_id: UUID) -> RecordReport | None:
        listing = await self._source.listing(strategy_id, reader_id)
        if listing is None:
            return None
        fills = await self._source.author_fills([strategy_id])
        report = build_record_report(fills.get(strategy_id, ()), self._clock.now())
        if report.unresolved_allocation_ids:
            logger.warning(
                "public strategy %s leaves out of its record %d trade(s) whose symbol "
                "cannot be split against the settlement currency: %s",
                strategy_id,
                len(report.unresolved_allocation_ids),
                ", ".join(str(each) for each in report.unresolved_allocation_ids),
            )
        return report

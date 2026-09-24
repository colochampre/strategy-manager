"""``ReadRecordedFillIds``: implements
``reconciliation.application.ports.RecordedFillIdsPort`` by asking the
repository which of a candidate set of fill ids ``ledger_entries`` already
holds.

Sibling of ``ReadSymbolPositions`` -- both are thin adapters translating a
``reconciliation``-declared port into a call on ``ledger``'s own internal
reader port; the real query lives in ``SqlAlchemyLedgerRepository``, not
here.
"""

from collections.abc import Sequence

from strategy_manager.ledger.application.ports import RecordedFillIdsReaderPort


class ReadRecordedFillIds:
    """Implements ``reconciliation.application.ports.RecordedFillIdsPort``."""

    def __init__(self, reader: RecordedFillIdsReaderPort) -> None:
        self._reader = reader

    async def recorded_fill_ids(
        self, exchange: str, venue: str, exchange_fill_ids: Sequence[str]
    ) -> frozenset[str]:
        return await self._reader.recorded_fill_ids(exchange, venue, exchange_fill_ids)

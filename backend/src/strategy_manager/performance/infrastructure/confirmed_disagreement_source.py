"""``ConfirmedDisagreementSource``: the open ``CONFIRMED`` rows of the
reconciliation's discrepancies, mapped to the port's record (design addendum
"open positions", sections E and G).

A thin adapter over ``list_discrepancies(status=CONFIRMED, open_only=True)``, the
call ``PrepareBooking`` already makes: ONE statement, read once per request, and
no venue is read and nothing is written. The reconciliation's own record
(``DiscrepancyRecord``) is known to this file alone; the use case sees
``DiscrepancyRow``.

The repository's filter is not trusted for the mark's rule: the row carries its
status and its ``resolved_at`` so that ``venue_disagreement_for`` still decides
(an OBSERVED or a resolved row marks nothing, whoever hands it over).
"""

from collections.abc import Sequence

from strategy_manager.performance.domain.open_position import DiscrepancyRow, PoolLabel
from strategy_manager.reconciliation.application.ports import (
    DiscrepancyRecord,
    DiscrepancyRepositoryPort,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyStatus


class ConfirmedDisagreementSource:
    """Implements ``ConfirmedDisagreementSourcePort``."""

    def __init__(self, discrepancies: DiscrepancyRepositoryPort) -> None:
        self._discrepancies = discrepancies

    async def confirmed_open(self) -> Sequence[DiscrepancyRow]:
        records = await self._discrepancies.list_discrepancies(
            status=DiscrepancyStatus.CONFIRMED, open_only=True
        )
        return [_row(record) for record in records]


def _row(record: DiscrepancyRecord) -> DiscrepancyRow:
    return DiscrepancyRow(
        discrepancy_id=record.id,
        pool=PoolLabel(record.exchange, record.venue, record.settlement_currency),
        symbol=record.symbol,
        status=record.status.value,
        venue_net_base=record.venue_net_base,
        ledger_net_base=record.ledger_net_base,
        open_allocation_ids=record.open_allocation_ids,
        last_observed_at=record.last_observed_at,
        resolved_at=record.resolved_at,
    )

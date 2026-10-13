"""``ConfirmedDisagreementSource``: the open ``CONFIRMED`` rows of the
reconciliation's discrepancies, mapped to the port's record (design addendum
"open positions", section E and G).

STUB: typed and importable, and it answers nothing. Replaced by the real
mapping in the GREEN commit.
"""

from collections.abc import Sequence

from strategy_manager.performance.domain.open_position import DiscrepancyRow
from strategy_manager.reconciliation.application.ports import DiscrepancyRepositoryPort


class ConfirmedDisagreementSource:
    """Implements ``ConfirmedDisagreementSourcePort``."""

    def __init__(self, discrepancies: DiscrepancyRepositoryPort) -> None:
        self._discrepancies = discrepancies

    async def confirmed_open(self) -> Sequence[DiscrepancyRow]:
        return []

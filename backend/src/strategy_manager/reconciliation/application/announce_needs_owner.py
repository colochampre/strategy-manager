"""``AnnounceNeedsOwner``: tells the owner, in one ERROR record, about the
open CONFIRMED discrepancies that need them (design.md PR 15 addendum § E;
owner decision 66 Q3 and Q4, 2026-10-16).

The record names pool, symbol, kind, reason code with its fixed phrase and
discrepancy id -- never a quantity, a price or a fee.
"""

import logging
from collections.abc import Mapping
from uuid import UUID

from strategy_manager.reconciliation.domain.booking import BookingRefusal

logger = logging.getLogger(__name__)


class AnnounceNeedsOwner:
    async def run(self, last_reason_by_discrepancy: Mapping[UUID, BookingRefusal]) -> None:
        return None

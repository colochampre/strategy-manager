"""``AnnounceNeedsOwner``: tells the owner, in one ERROR record, about the
open CONFIRMED discrepancies that need them (design.md PR 15 addendum § E;
owner decision 66 Q3 and Q4, 2026-10-16).

The record names pool, symbol, kind, reason code with its fixed phrase and
discrepancy id -- never a quantity, a price or a fee.

**The throttle key stays one key.** The alert bridge throttles per (logger
name, ``record.msg``), the message TEMPLATE. The announcement's template is a
constant and the whole list of items, reasons included, is its single
argument, so a reason never mints a new throttle key.

**Once per start of the worker.** What was announced is process-scoped and
module-level, for the reason ``booking_prepare_handler._SkipAnnouncement``
gives: ``main.py`` builds a fresh handler (and so a fresh use case) for every
job. An id that stops needing the owner is dropped from it, so a recurrence
is announced again.

The module's own ``strategy_manager.reconciliation...`` logger is used on
purpose: it must never sit under ``strategy_manager.alerts``, which the bridge
drops.
"""

import logging
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from strategy_manager.reconciliation.application.ports import (
    ApprovedObservationsPort,
    DiscrepancyRecord,
    DiscrepancyRepositoryPort,
)
from strategy_manager.reconciliation.domain.attention import (
    AttentionGroup,
    ConfirmedRow,
    NeedsOwnerReason,
    sort_confirmed,
)
from strategy_manager.reconciliation.domain.booking import BOOKING_REFUSAL_PHRASES, BookingRefusal
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)

#: One constant template per record kind (design § E). They MUST differ, or
#: the bridge's per-template throttle folds a reminder into an announcement.
ANNOUNCEMENT_TEMPLATE = "confirmed discrepancies need the owner: %s"
REMINDER_TEMPLATE = "reminder: %d confirmed discrepancies still need the owner: %s"

_NOT_BOOKABLE_PHRASE = "the venue difference is of a kind this system never books"
_REASON_UNKNOWN_PHRASE = "see the worker log"


@dataclass(slots=True)
class _Memory:
    announced: set[UUID] = field(default_factory=set)
    last_notice_at: datetime | None = None


_memory = _Memory()


def reset_announcements() -> None:
    """For tests, which must not inherit another test's announcements."""

    _memory.announced.clear()
    _memory.last_notice_at = None


@dataclass(frozen=True, slots=True)
class _Item:
    discrepancy_id: UUID
    text: str


def _reason(
    reason: NeedsOwnerReason,
    discrepancy_id: UUID,
    kind: DiscrepancyKind,
    known: MutableMapping[UUID, BookingRefusal],
) -> tuple[str, str]:
    """The code and the fixed English phrase of one NEEDS_OWNER item."""

    if reason is NeedsOwnerReason.NOT_BOOKABLE:
        # Design § E: "NOT_BOOKABLE with the kind".
        return NeedsOwnerReason.NOT_BOOKABLE.value, f"{_NOT_BOOKABLE_PHRASE}: {kind.value}"
    if reason is NeedsOwnerReason.SEVERAL_ALLOCATIONS:
        return (
            BookingRefusal.SEVERAL_ALLOCATIONS.value,
            BOOKING_REFUSAL_PHRASES[BookingRefusal.SEVERAL_ALLOCATIONS],
        )
    refusal = known.get(discrepancy_id)
    if refusal is None:
        return NeedsOwnerReason.REASON_UNKNOWN.value, _REASON_UNKNOWN_PHRASE
    return refusal.value, BOOKING_REFUSAL_PHRASES[refusal]


def _item(
    row: DiscrepancyRecord, reason: NeedsOwnerReason, known: MutableMapping[UUID, BookingRefusal]
) -> _Item:
    code, phrase = _reason(reason, row.id, row.kind, known)
    text = (
        f"{row.exchange}/{row.venue}/{row.settlement_currency} {row.symbol} {row.kind.value}: "
        f"{code} ({phrase}) [{row.id}]"
    )
    return _Item(row.id, text)


class AnnounceNeedsOwner:
    def __init__(
        self,
        discrepancies: DiscrepancyRepositoryPort,
        approved: ApprovedObservationsPort,
        clock: ClockPort,
        grace_seconds: int,
        reminder_seconds: int,
    ) -> None:
        self._discrepancies = discrepancies
        self._approved = approved
        self._clock = clock
        self._grace = timedelta(seconds=grace_seconds)
        self._reminder = timedelta(seconds=reminder_seconds)

    async def run(self, last_reason_by_discrepancy: MutableMapping[UUID, BookingRefusal]) -> None:
        rows = await self._discrepancies.list_discrepancies(
            status=DiscrepancyStatus.CONFIRMED, open_only=True
        )
        open_ids = {row.id for row in rows}
        # A discrepancy that is no longer open has no reason worth keeping.
        for stale in [i for i in last_reason_by_discrepancy if i not in open_ids]:
            del last_reason_by_discrepancy[stale]

        approved = await self._approved.approved_observations([row.id for row in rows])
        now = self._clock.now()

        needing: list[_Item] = []
        for row in rows:
            attention = sort_confirmed(
                ConfirmedRow(
                    status=row.status,
                    resolved=row.resolved_at is not None,
                    observation=Observation(row.kind, row.venue_net_base, row.ledger_net_base),
                    open_allocation_count=len(row.open_allocation_ids),
                    confirmed_at=row.confirmed_at,
                    approved_observations=approved.get(row.id, ()),
                ),
                now,
                self._grace,
            )
            if (
                attention is None
                or attention.group is not AttentionGroup.NEEDS_OWNER
                or attention.reason is None
            ):
                continue
            needing.append(_item(row, attention.reason, last_reason_by_discrepancy))

        # An id that stopped needing the owner is forgotten, so a recurrence
        # is announced anew (decision 66 Q4: once per start, per discrepancy).
        _memory.announced &= {item.discrepancy_id for item in needing}

        new = [item for item in needing if item.discrepancy_id not in _memory.announced]
        if new:
            logger.error(ANNOUNCEMENT_TEMPLATE, "; ".join(item.text for item in new))
            _memory.announced.update(item.discrepancy_id for item in new)
            _memory.last_notice_at = now
            return

        # The daily reminder: while anything needs the owner, at most one
        # ERROR per interval lists every such item, timed from the process's
        # last announcement or reminder. Its template is its OWN constant so
        # the bridge's throttle cannot fold it into an announcement made in
        # the same window (K row 9).
        if (
            needing
            and _memory.last_notice_at is not None
            and now - _memory.last_notice_at >= self._reminder
        ):
            logger.error(REMINDER_TEMPLATE, len(needing), "; ".join(i.text for i in needing))
            _memory.last_notice_at = now

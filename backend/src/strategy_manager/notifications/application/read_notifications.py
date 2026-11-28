"""``ReadNotifications``: the signed-in user's feed (panel-redesign RD.5a).

The feed is every source's items put in one order, so it is read whole and cut
afterwards, as ``ReadMyTrades`` reads every closed operation to count and order
them. Only the sources the asked kind needs are read: ``kind=NOTICE`` reads the
deliveries and nothing else, and ``kind=DISCREPANCY`` for a user who is not the
admin reads nothing at all, so a non-admin never causes the whole-system
reconciliation read to run.

What each source gives, and the one rule each keeps, are in the contract of
RD.5 (``openspec/changes/panel-redesign/tasks.md``):

* an operation gives ``OPENED`` at its opening (when that instant is known) and,
  once closed, ``CLOSED``; a close whose cause is the user's or the strategy's own
  is an ``OPERATION`` item and any other cause is a ``SAFETY`` item. A close is
  listed from the trades alone, never again from the safety events;
* a refused opening is a ``SAFETY`` item from the safety events, and a ``NOTICE``
  item from a rejected delivery whose reason is in ``NOTICE_REASONS``, an
  allow-list: a reason that is not on it is not something the user can fix;
* a seat an author's wider stop lowered (RD.9a) is a ``NOTICE`` item of the seat's
  owner alone, from its event: ``reason`` ``STOP_CHANGED``, ``leverage`` the new one and
  ``detail`` the old and the new, as strings;
* a discrepancy that needs the owner is a ``DISCREPANCY`` item for the admin, and
  none while the reconciliation reads ``dry_run``.
"""

from collections.abc import Collection
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from strategy_manager.execution.domain.market_symbol import market_key
from strategy_manager.notifications.application.ports import (
    DiscrepancySourcePort,
    LoweredSeatFacts,
    LoweredSeatSourcePort,
    NoticeFacts,
    NoticeSourcePort,
    OperationFacts,
    OperationSourcePort,
    RefusalFacts,
    RefusalSourcePort,
)
from strategy_manager.notifications.domain.notification import (
    Cursor,
    FeedPage,
    NotificationEvent,
    NotificationItem,
    NotificationKind,
    kind_of_close,
    page_of,
    unseen_kinds,
)
from strategy_manager.shared.domain.safety_event import SafetyEventKind

DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100

#: The only rejection reasons that become a notice: each is something the user can
#: put right (link a key that can trade, isolate the margin, set the leverage).
NOTICE_REASONS: tuple[str, ...] = (
    "EXCHANGE_HAS_NO_KEY",
    "EXCHANGE_KEY_READ_ONLY",
    "MARGIN_NOT_ISOLATED",
    "LEVERAGE_CONFLICT",
    "LEVERAGE_NOT_APPLIED",
)

#: The safety events that refuse an opening. The close kinds are not read from the
#: events: a close comes from the trades, with its cause.
REFUSAL_KINDS: tuple[SafetyEventKind, ...] = (
    SafetyEventKind.OPENING_REFUSED_LEVERAGE_CAP,
    SafetyEventKind.OPENING_REFUSED_ACCOUNT_SUSPENDED,
    SafetyEventKind.OPENING_REFUSED_AUTHOR_SUSPENDED,
)

_FROM_OPERATIONS = frozenset({NotificationKind.OPERATION, NotificationKind.SAFETY})


class ReadNotifications:
    def __init__(
        self,
        operations: OperationSourcePort,
        refusals: RefusalSourcePort,
        notices: NoticeSourcePort,
        discrepancies: DiscrepancySourcePort,
        lowered_seats: LoweredSeatSourcePort,
    ) -> None:
        self._operations = operations
        self._refusals = refusals
        self._notices = notices
        self._lowered_seats = lowered_seats
        self._discrepancies = discrepancies

    async def read(
        self,
        user_id: UUID,
        *,
        is_admin: bool,
        limit: int = DEFAULT_PAGE_SIZE,
        after: Cursor | None = None,
        kind: NotificationKind | None = None,
    ) -> FeedPage:
        wanted = frozenset(NotificationKind) if kind is None else frozenset({kind})
        items = await self._items(user_id, is_admin, wanted)
        return page_of([item for item in items if kind is None or item.kind is kind], limit, after)

    async def unseen(
        self, user_id: UUID, *, is_admin: bool, since: datetime
    ) -> tuple[NotificationKind, ...]:
        items = await self._items(user_id, is_admin, frozenset(NotificationKind))
        return unseen_kinds(items, since)

    async def _items(
        self, user_id: UUID, is_admin: bool, wanted: Collection[NotificationKind]
    ) -> list[NotificationItem]:
        items: list[NotificationItem] = []
        if _FROM_OPERATIONS.intersection(wanted):
            for operation in await self._operations.operations(user_id):
                items += _operation_items(operation)
        if NotificationKind.SAFETY in wanted:
            items += [_refusal_item(r) for r in await self._refusals.refusals(user_id)]
        if NotificationKind.NOTICE in wanted:
            notices = await self._notices.notices(user_id, NOTICE_REASONS)
            items += [_notice_item(n) for n in notices]
            items += [_lowered_item(s) for s in await self._lowered_seats.lowered(user_id)]
        if NotificationKind.DISCREPANCY in wanted and is_admin:
            reading = await self._discrepancies.needs_owner()
            if not reading.dry_run:
                items += [
                    NotificationItem(
                        id=f"discrepancy:{d.discrepancy_id}",
                        kind=NotificationKind.DISCREPANCY,
                        event=NotificationEvent.DISCREPANCY,
                        occurred_at=d.occurred_at,
                        reason=d.kind,
                        exchange=d.exchange,
                        venue=d.venue,
                        pair=market_key(d.symbol),
                        currency=d.currency,
                    )
                    for d in reading.needs_owner
                ]
        return items


def _operation_items(operation: OperationFacts) -> list[NotificationItem]:
    common: dict[str, Any] = {
        "strategy_id": None if operation.strategy_id is None else str(operation.strategy_id),
        "strategy_name": operation.strategy_name,
        "exchange": operation.exchange,
        "venue": operation.venue,
        "pair": operation.pair,
        "side": operation.side,
        "rehearsal": operation.rehearsal,
        "currency": operation.currency,
    }
    items: list[NotificationItem] = []
    if operation.opened_at is not None:
        items.append(
            NotificationItem(
                id=f"opened:{operation.allocation_id}",
                kind=NotificationKind.OPERATION,
                event=NotificationEvent.OPENED,
                occurred_at=operation.opened_at,
                entry_price=operation.entry_price,
                leverage=operation.leverage,
                **common,
            )
        )
    if operation.closed is not None:
        closed = operation.closed
        items.append(
            NotificationItem(
                id=f"closed:{operation.allocation_id}",
                kind=kind_of_close(closed.close_cause),
                event=NotificationEvent.CLOSED,
                occurred_at=closed.closed_at,
                exit_price=closed.exit_price,
                pnl=closed.pnl,
                close_cause=closed.close_cause,
                **common,
            )
        )
    return items


def _refusal_item(refusal: RefusalFacts) -> NotificationItem:
    return NotificationItem(
        id=f"refused:{refusal.event_id}",
        kind=NotificationKind.SAFETY,
        event=NotificationEvent.OPENING_REFUSED,
        occurred_at=refusal.occurred_at,
        reason=refusal.kind,
        strategy_id=str(refusal.strategy_id),
        strategy_name=refusal.strategy_name,
        exchange=refusal.exchange,
        venue=refusal.venue,
        pair=market_key(refusal.symbol),
        detail=dict(refusal.detail),
    )


def _notice_item(notice: NoticeFacts) -> NotificationItem:
    return NotificationItem(
        id=f"notice:{notice.delivery_id}",
        kind=NotificationKind.NOTICE,
        event=NotificationEvent.OPENING_REFUSED,
        occurred_at=notice.decided_at,
        reason=notice.reason,
        strategy_id=str(notice.strategy_id),
        strategy_name=notice.strategy_name,
        exchange=notice.exchange,
        venue=notice.venue,
        pair=market_key(notice.symbol),
        currency=notice.currency,
    )


#: The one reason a lowered seat gives: the author's stop moved the cap under it.
LOWERED_REASON = "STOP_CHANGED"


def _lowered_item(seat: LoweredSeatFacts) -> NotificationItem:
    return NotificationItem(
        id=f"lowered:{seat.event_id}",
        kind=NotificationKind.NOTICE,
        event=NotificationEvent.LEVERAGE_LOWERED,
        occurred_at=seat.occurred_at,
        reason=LOWERED_REASON,
        strategy_id=str(seat.strategy_id),
        strategy_name=seat.strategy_name,
        leverage=Decimal(seat.new_leverage),
        detail={"from": str(seat.old_leverage), "to": str(seat.new_leverage)},
    )

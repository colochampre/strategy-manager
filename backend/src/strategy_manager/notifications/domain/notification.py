"""What a notification is, and how a feed of them is ordered, cut and summarised
(panel-redesign RD.5a). Pure: no framework, no I/O, and no knowledge of where an
item came from.

An item is one thing that happened to one user: an operation opened or closed,
an opening that was refused, or (for the admin) a discrepancy that needs a
decision. Its ``id`` is stable and says what it is about, so the panel can tell
a repeat from a new one: ``opened:<allocation>``, ``closed:<allocation>``,
``refused:<safety event>``, ``notice:<delivery>``, ``lowered:<leverage event>``,
``discrepancy:<discrepancy>``.

**Order.** Newest first by ``occurred_at``, then by ``id`` descending: the id
breaks a tie between two items at one instant, so a page boundary never lands
between two items the order cannot tell apart. ``Cursor`` carries both halves.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class NotificationKind(StrEnum):
    OPERATION = "OPERATION"
    SAFETY = "SAFETY"
    NOTICE = "NOTICE"
    DISCREPANCY = "DISCREPANCY"


class NotificationEvent(StrEnum):
    OPENED = "OPENED"
    CLOSED = "CLOSED"
    OPENING_REFUSED = "OPENING_REFUSED"
    LEVERAGE_LOWERED = "LEVERAGE_LOWERED"
    DISCREPANCY = "DISCREPANCY"


#: The order ``unseen`` answers in: what asks the most of the user first.
UNSEEN_ORDER: tuple[NotificationKind, ...] = (
    NotificationKind.SAFETY,
    NotificationKind.DISCREPANCY,
    NotificationKind.NOTICE,
    NotificationKind.OPERATION,
)

#: The closes that are the user's or their strategy's own doing. Every other
#: cause is the system protecting the user's money, and is a safety item.
OPERATION_CLOSE_CAUSES: frozenset[str] = frozenset({"SIGNAL", "MANUAL_CLOSE"})


def kind_of_close(close_cause: str) -> NotificationKind:
    return (
        NotificationKind.OPERATION
        if close_cause in OPERATION_CLOSE_CAUSES
        else NotificationKind.SAFETY
    )


@dataclass(frozen=True, slots=True)
class NotificationItem:
    """Any of the strategy, market and figure fields is ``None`` where the item's
    source has none. ``detail`` holds strings only."""

    id: str
    kind: NotificationKind
    event: NotificationEvent
    occurred_at: datetime
    reason: str | None = None
    strategy_id: str | None = None
    strategy_name: str | None = None
    exchange: str | None = None
    venue: str | None = None
    pair: str | None = None
    side: str | None = None
    rehearsal: bool = False
    currency: str | None = None
    entry_price: Decimal | None = None
    exit_price: Decimal | None = None
    pnl: Decimal | None = None
    leverage: Decimal | None = None
    close_cause: str | None = None
    detail: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Cursor:
    """The position of the last item of a page."""

    occurred_at: datetime
    id: str


def _key(item: NotificationItem) -> tuple[datetime, str]:
    return (item.occurred_at, item.id)


def newest_first(items: Sequence[NotificationItem]) -> list[NotificationItem]:
    return sorted(items, key=_key, reverse=True)


@dataclass(frozen=True, slots=True)
class FeedPage:
    items: tuple[NotificationItem, ...]
    next_cursor: Cursor | None


def page_of(items: Sequence[NotificationItem], limit: int, after: Cursor | None) -> FeedPage:
    """The ``limit`` items that come after ``after`` in the newest-first order, and
    the cursor of the last one when more follow it."""
    ordered = newest_first(items)
    if after is not None:
        ordered = [item for item in ordered if _key(item) < (after.occurred_at, after.id)]
    page = ordered[:limit]
    more = len(ordered) > limit
    last = page[-1] if page else None
    return FeedPage(
        items=tuple(page),
        next_cursor=Cursor(last.occurred_at, last.id) if more and last is not None else None,
    )


def unseen_kinds(
    items: Sequence[NotificationItem], since: datetime
) -> tuple[NotificationKind, ...]:
    """The distinct kinds of the items that happened after ``since``, in
    ``UNSEEN_ORDER``."""
    present = {item.kind for item in items if item.occurred_at > since}
    return tuple(kind for kind in UNSEEN_ORDER if kind in present)

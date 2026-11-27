"""``/notifications``: the signed-in user's feed (panel-redesign RD.5a).

Two reads, both the signed-in user's own and neither an admin route:

- ``GET /notifications``: the feed, newest first, in cursor pages. Query:
  ``limit`` (1 to 100, default 30), ``cursor`` (opaque, the previous page's
  ``next_cursor``; a malformed one is a 422) and ``kind``.
- ``GET /notifications/unseen``: the distinct kinds of the items after ``since``
  (an aware datetime; a naive one is a 422), in the order ``SAFETY``,
  ``DISCREPANCY``, ``NOTICE``, ``OPERATION``.

**Whose.** The user id comes from ``current_user`` and is every source's argument.
The one whole-system source, the reconciliation's discrepancies, is asked for an
admin only, decided here from the user's e-mail as ``/me`` does: a user who is not
the admin gets no such item, and ``kind=DISCREPANCY`` is an empty page for them,
never a 403. The route has no ``require_admin``.

**Read only.** Nothing is written, no credential is read and no exchange is
called. A read that finds stored data inconsistent (``InvariantViolation``) is a
fixed 500 that echoes nothing, with one ``ERROR`` in the log, as the performance
reads answer it.
"""

import base64
import binascii
import json
import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user, is_admin
from strategy_manager.notifications.application.read_notifications import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ReadNotifications,
)
from strategy_manager.notifications.domain.notification import (
    Cursor,
    FeedPage,
    NotificationItem,
    NotificationKind,
)
from strategy_manager.notifications.infrastructure.sources import (
    ReconciliationDiscrepancySource,
    SqlAlchemyNoticeSource,
    SqlAlchemyOperationSource,
    SqlAlchemyRefusalSource,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.errors import InvariantViolation
from strategy_manager.shared.infrastructure.wire import Instant, Money, Price

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    dependencies=[Depends(current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

INTEGRITY_FAULT_DETAIL = "notifications data failed an integrity check"
MALFORMED_CURSOR_DETAIL = "the cursor is not one this feed gave"


def get_read_notifications(session: SessionDep, settings: SettingsDep) -> ReadNotifications:
    return ReadNotifications(
        SqlAlchemyOperationSource(session),
        SqlAlchemyRefusalSource(session),
        SqlAlchemyNoticeSource(session),
        ReconciliationDiscrepancySource(session, settings),
    )


ReaderDep = Annotated[ReadNotifications, Depends(get_read_notifications)]


# --- the cursor ---------------------------------------------------------------------------


def encode_cursor(cursor: Cursor) -> str:
    """Opaque to the client: URL-safe base64 of the last item's instant and id."""
    payload = json.dumps({"t": cursor.occurred_at.isoformat(), "i": cursor.id})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(text: str) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
        data = json.loads(raw)
        occurred_at = datetime.fromisoformat(data["t"])
        item_id = data["i"]
    except (ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail=MALFORMED_CURSOR_DETAIL) from exc
    if occurred_at.tzinfo is None or not isinstance(item_id, str):
        raise HTTPException(status_code=422, detail=MALFORMED_CURSOR_DETAIL)
    return Cursor(occurred_at, item_id)


# --- bodies -------------------------------------------------------------------------------


class NotificationBody(BaseModel):
    """One thing that happened to the user. Every figure is a string on the wire;
    any of the strategy, market and figure fields is null where the source has
    none. ``detail`` holds strings only."""

    id: str
    kind: Literal["OPERATION", "SAFETY", "NOTICE", "DISCREPANCY"]
    event: Literal["OPENED", "CLOSED", "OPENING_REFUSED", "DISCREPANCY"]
    occurred_at: Instant
    reason: str | None
    strategy_id: UUID | None
    strategy_name: str | None
    exchange: str | None
    venue: str | None
    pair: str | None
    side: Literal["LONG", "SHORT"] | None
    rehearsal: bool
    currency: str | None
    entry_price: Price | None
    exit_price: Price | None
    pnl: Money | None
    leverage: Money | None
    close_cause: str | None
    detail: dict[str, str]

    @classmethod
    def of(cls, item: NotificationItem) -> "NotificationBody":
        return cls(
            id=item.id,
            kind=item.kind.value,
            event=item.event.value,
            occurred_at=item.occurred_at,
            reason=item.reason,
            strategy_id=None if item.strategy_id is None else UUID(item.strategy_id),
            strategy_name=item.strategy_name,
            exchange=item.exchange,
            venue=item.venue,
            pair=item.pair,
            side=None if item.side is None else _side(item.side),
            rehearsal=item.rehearsal,
            currency=item.currency,
            entry_price=item.entry_price,
            exit_price=item.exit_price,
            pnl=item.pnl,
            leverage=item.leverage,
            close_cause=item.close_cause,
            detail=dict(item.detail),
        )


def _side(side: str) -> Literal["LONG", "SHORT"]:
    if side == "LONG":
        return "LONG"
    if side == "SHORT":
        return "SHORT"
    raise InvariantViolation(f"a side is LONG or SHORT, not {side!r}")


class NotificationsBody(BaseModel):
    items: list[NotificationBody]
    next_cursor: str | None

    @classmethod
    def of(cls, page: FeedPage) -> "NotificationsBody":
        return cls(
            items=[NotificationBody.of(item) for item in page.items],
            next_cursor=None if page.next_cursor is None else encode_cursor(page.next_cursor),
        )


class UnseenBody(BaseModel):
    kinds: list[Literal["OPERATION", "SAFETY", "NOTICE", "DISCREPANCY"]]


def _fault(exc: InvariantViolation) -> HTTPException:
    logger.error("notifications read refused: %s", exc)
    return HTTPException(status_code=500, detail=INTEGRITY_FAULT_DETAIL)


# --- routes -------------------------------------------------------------------------------


@router.get("", response_model=NotificationsBody)
async def read_notifications(
    reader: ReaderDep,
    user: Annotated[User, Depends(current_user)],
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: str | None = None,
    kind: NotificationKind | None = None,
) -> NotificationsBody:
    after = None if cursor is None else decode_cursor(cursor)
    try:
        page = await reader.read(
            user.id,
            is_admin=is_admin(user.email, settings),
            limit=limit,
            after=after,
            kind=kind,
        )
    except InvariantViolation as exc:
        raise _fault(exc) from exc
    return NotificationsBody.of(page)


@router.get("/unseen", response_model=UnseenBody)
async def read_unseen(
    reader: ReaderDep,
    user: Annotated[User, Depends(current_user)],
    settings: SettingsDep,
    since: Annotated[AwareDatetime, Query()],
) -> UnseenBody:
    try:
        kinds = await reader.unseen(user.id, is_admin=is_admin(user.email, settings), since=since)
    except InvariantViolation as exc:
        raise _fault(exc) from exc
    return UnseenBody(kinds=[kind.value for kind in kinds])

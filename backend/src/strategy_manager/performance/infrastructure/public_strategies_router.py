"""``GET /public/strategies`` and ``GET /public/strategies/{id}``: what any
signed-in user may read of a strategy on the public list (tasks.md F.4, decisions
15, 27, 28 and 30).

**A body is an explicit list.** ``PublicStrategyBody`` is built field by field from
what ``PublicStrategiesSourcePort`` selected, so no ``author_id``, e-mail, secret
hint or subscriber row can reach it, and
``test_public_strategies_router.py`` pins its keys.

**One 404.** A strategy that is private, archived, or of an unnamed author answers
what an unknown id answers, to everyone and to its own author, who has their own
page. Nobody can tell one of those from a strategy that does not exist. The one
exception is a strategy turned private, to a reader who holds a live seat on it: its
page and record still answer them, since the page is where that seat is managed
(tasks.md J.1, decision 21). It stays off the list.

**A link or a code** opens a strategy off the list too (decision 41, tasks.md K.4):
``?link=`` its current token for a LINK strategy, ``?code=`` a live code made for a
LINK or PRIVATE one. The code is read only when the strategy does not open without
it. A wrong code answers the same 404; a dead one answers 410 with why, and a reader
who got ``MAX_FAILED_ATTEMPTS`` codes wrong in the last hour gets 429.

**A return the wire cannot write** answers that same 404, and leaves the list, with
a log line. An alert's price is whatever its sender writes, so one strategy can
compound past what ``ratio`` rounds, and it must not cost everyone the whole list
(tasks.md G.1).

**The return says what it is.** ``unleveraged_return_before_fees`` is a fraction
that reads as if the whole capital were on each trade, and its name carries both
limits so that no client can show it without them. Zero closed trades answers
zero: whether that reads as "0 %" or "no record yet" is the panel's.

**The capital** is in ``settlement_currency``, and null under the ``DRY_RUN`` brake,
when nobody trades live. ``created_at`` is the strategy's age.

``GET /public/strategies/{id}/record`` (tasks.md I.12a) draws that same record: origin,
curve, months, ranges and pairs, from the author's real fills, with no amount in it.
It answers the same 404 as the page, including when a figure does not fit the wire.

All three routes read in one read-only ``REPEATABLE READ`` snapshot.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import date as calendar_date
from decimal import InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pydantic_core import PydanticSerializationError

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.performance.application.ports import (
    PageEntry,
    PublicStrategiesSourcePort,
)
from strategy_manager.performance.application.read_public_record import ReadPublicRecord
from strategy_manager.performance.application.read_public_strategies import (
    PublicStrategy,
    ReadPublicStrategies,
)
from strategy_manager.performance.domain.public_record import RecordReport
from strategy_manager.performance.infrastructure.open_positions_router import (
    SnapshotSessionDep,
)
from strategy_manager.performance.infrastructure.performance_router import (
    ClockDep,
    CurvePointBody,
    MonthBody,
)
from strategy_manager.performance.infrastructure.public_strategies_source import (
    SqlAlchemyPublicStrategiesSource,
)
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.wire import Instant, Money, Ratio, ratio
from strategy_manager.strategies.application.code_entry import CheckInviteCode
from strategy_manager.strategies.domain.invite_code import (
    InviteCodeNotLive,
    TooManyCodeAttempts,
)
from strategy_manager.strategies.infrastructure.code_entry_http import (
    CodeCheckDep,
    CodeQuery,
    LinkQuery,
    code_refusal,
)
from strategy_manager.strategies.infrastructure.uptime_view import UptimeView

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/public/strategies",
    tags=["public"],
    dependencies=[Depends(current_user)],
)


def get_public_source(session: SnapshotSessionDep) -> PublicStrategiesSourcePort:
    return SqlAlchemyPublicStrategiesSource(session)


SourceDep = Annotated[PublicStrategiesSourcePort, Depends(get_public_source)]
#: The signed-in reader: the page and the record of a strategy turned private still answer
#: to a reader with a live seat on it (tasks.md J.1). The router's own dependency is the
#: same call, which FastAPI resolves once per request.
ReaderDep = Annotated[User, Depends(current_user)]


class PublicStrategyBody(BaseModel):
    id: UUID
    name: str
    # Plain text, for the panel to render as text and never as HTML or Markdown.
    description: str | None
    author_name: str
    exchange: str
    venue: str
    settlement_currency: str
    created_at: Instant
    closed_trade_count: int
    unleveraged_return_before_fees: Ratio
    live_subscribers: int
    capital: Money | None
    # tasks.md L.1: every ACTIVE seat, live or not; the record's deepest fall and
    # win rate (None with no closed trade); whether the author has it running.
    subscribers: int
    max_drawdown: Ratio
    win_rate: Ratio | None
    enabled: bool
    # The days active beside the age, as the author's own card reads them (tasks.md L.1).
    uptime: UptimeView
    # The cap on the leverage a reader may choose (subscriber-safety D5).
    stop_loss_pct: Money


def _body(strategy: PublicStrategy) -> PublicStrategyBody:
    listing = strategy.listing
    return PublicStrategyBody(
        id=listing.strategy_id,
        name=listing.name,
        description=listing.description,
        author_name=listing.author_name,
        exchange=listing.exchange,
        venue=listing.venue,
        settlement_currency=listing.settlement_currency,
        created_at=listing.created_at,
        closed_trade_count=strategy.record.closed_trade_count,
        unleveraged_return_before_fees=strategy.record.total_return,
        live_subscribers=strategy.live_subscribers,
        capital=strategy.capital,
        subscribers=listing.subscribers,
        max_drawdown=strategy.record.max_drawdown,
        win_rate=strategy.record.win_rate,
        enabled=listing.enabled,
        uptime=UptimeView.of(strategy.uptime),
        stop_loss_pct=listing.stop_loss_pct,
    )


def _reader(source: PublicStrategiesSourcePort, clock: ClockPort) -> ReadPublicStrategies:
    return ReadPublicStrategies(source, brake=get_settings().dry_run, clock=clock)


def _writable(strategy: PublicStrategy) -> bool:
    try:
        ratio(strategy.record.total_return)
    except InvalidOperation:
        logger.warning(
            "public strategy %s is off the list: its return does not fit the wire",
            strategy.listing.strategy_id,
        )
        return False
    return True


@router.get("", response_model=list[PublicStrategyBody])
async def list_public_strategies(source: SourceDep, clock: ClockDep) -> list[PublicStrategyBody]:
    return [
        _body(strategy)
        for strategy in await _reader(source, clock).read_all()
        if _writable(strategy)
    ]


class RecordRangeBody(BaseModel):
    range: str
    value: Ratio = Field(serialization_alias="return")
    trade_count: int


class RecordPairBody(BaseModel):
    pair: str
    trades: int
    wins: int
    win_rate: Ratio
    value: Ratio = Field(serialization_alias="return")


class PublicRecordBody(BaseModel):
    """The shared parts keep the names of the private report (``PerformanceBody``), so
    the panel draws both with the same components. Every amount is left out."""

    day_boundary: Literal["UTC"] = "UTC"
    origin: calendar_date | None
    closed_trade_count: int
    max_drawdown: Ratio
    ranges: list[RecordRangeBody]
    curve: list[CurvePointBody]
    monthly: list[MonthBody]
    by_pair: list[RecordPairBody]

    @classmethod
    def of(cls, report: RecordReport) -> "PublicRecordBody":
        return cls(
            origin=report.origin,
            closed_trade_count=report.closed_trade_count,
            max_drawdown=report.max_drawdown,
            ranges=[
                RecordRangeBody(range=r.range.value, value=r.value, trade_count=r.trade_count)
                for r in report.ranges
            ],
            curve=[
                CurvePointBody(
                    date=p.day, daily_return=p.daily_return, index=p.index, drawdown=p.drawdown
                )
                for p in report.curve
            ],
            monthly=[MonthBody(year=m.year, month=m.month, value=m.value) for m in report.monthly],
            by_pair=[
                RecordPairBody(
                    pair=p.pair,
                    trades=p.trade_count,
                    wins=p.win_count,
                    win_rate=p.win_rate,
                    value=p.value,
                )
                for p in report.by_pair
            ],
        )


async def _entered[T](
    strategy_id: UUID,
    reader: User,
    link: str | None,
    code: str | None,
    codes: CheckInviteCode,
    read: Callable[[PageEntry], Awaitable[T | None]],
) -> T | None:
    """What ``read`` answers for the reader, with the link they brought; the code only
    when that answers nothing, so a code is never read where it is not needed. A wrong
    code answers None, the 404 of no strategy; a dead one or the limit is refused."""
    found = await read(PageEntry(link=link))
    if found is not None or code is None:
        return found
    try:
        checked = await codes.check(reader.id, strategy_id, code)
    except (TooManyCodeAttempts, InviteCodeNotLive) as exc:
        raise code_refusal(exc) from exc
    if checked is None:
        return None
    return await read(PageEntry(link=link, code_checked=True))


@router.get("/{strategy_id}/record", response_model=PublicRecordBody, response_model_by_alias=True)
async def read_public_record(
    strategy_id: UUID,
    source: SourceDep,
    clock: ClockDep,
    reader: ReaderDep,
    codes: CodeCheckDep,
    link: LinkQuery = None,
    code: CodeQuery = None,
) -> PublicRecordBody:
    records = ReadPublicRecord(source, clock)
    report = await _entered(
        strategy_id,
        reader,
        link,
        code,
        codes,
        lambda entry: records.read(strategy_id, reader.id, entry),
    )
    if report is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    body = PublicRecordBody.of(report)
    try:
        body.model_dump(mode="json", by_alias=True)
    except (InvalidOperation, PydanticSerializationError):
        logger.warning(
            "public strategy %s has no record page: a figure of it does not fit the wire",
            strategy_id,
        )
        raise HTTPException(status_code=404, detail="no such strategy") from None
    return body


@router.get("/{strategy_id}", response_model=PublicStrategyBody)
async def read_public_strategy(
    strategy_id: UUID,
    source: SourceDep,
    clock: ClockDep,
    reader: ReaderDep,
    codes: CodeCheckDep,
    link: LinkQuery = None,
    code: CodeQuery = None,
) -> PublicStrategyBody:
    strategies = _reader(source, clock)
    strategy = await _entered(
        strategy_id,
        reader,
        link,
        code,
        codes,
        lambda entry: strategies.read_one(strategy_id, reader.id, entry),
    )
    if strategy is None or not _writable(strategy):
        raise HTTPException(status_code=404, detail="no such strategy")
    return _body(strategy)

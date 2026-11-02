"""``GET /public/strategies`` and ``GET /public/strategies/{id}``: what any
signed-in user may read of a strategy on the public list (tasks.md F.4, decisions
15, 27, 28 and 30).

**A body is an explicit list.** ``PublicStrategyBody`` is built field by field from
what ``PublicStrategiesSourcePort`` selected, so no ``author_id``, e-mail, secret
hint or subscriber row can reach it, and
``test_public_strategies_router.py`` pins its keys.

**One 404.** A strategy that is private, archived, or of an unnamed author answers
what an unknown id answers, to everyone and to its own author, who has their own
page. Nobody can tell one of those from a strategy that does not exist.

**The return says what it is.** ``unleveraged_return_before_fees`` is a fraction
that reads as if the whole capital were on each trade, and its name carries both
limits so that no client can show it without them. Zero closed trades answers
zero: whether that reads as "0 %" or "no record yet" is the panel's.

**The capital** is in ``settlement_currency``, and null under the ``DRY_RUN`` brake,
when nobody trades live. ``created_at`` is the strategy's age.

Both routes read in one read-only ``REPEATABLE READ`` snapshot.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.performance.application.ports import PublicStrategiesSourcePort
from strategy_manager.performance.application.read_public_strategies import (
    PublicStrategy,
    ReadPublicStrategies,
)
from strategy_manager.performance.infrastructure.open_positions_router import (
    SnapshotSessionDep,
)
from strategy_manager.performance.infrastructure.public_strategies_source import (
    SqlAlchemyPublicStrategiesSource,
)
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.infrastructure.wire import Instant, Money, Ratio

router = APIRouter(
    prefix="/public/strategies",
    tags=["public"],
    dependencies=[Depends(current_user)],
)


def get_public_source(session: SnapshotSessionDep) -> PublicStrategiesSourcePort:
    return SqlAlchemyPublicStrategiesSource(session)


SourceDep = Annotated[PublicStrategiesSourcePort, Depends(get_public_source)]


class PublicStrategyBody(BaseModel):
    id: UUID
    name: str
    author_name: str
    exchange: str
    venue: str
    settlement_currency: str
    created_at: Instant
    closed_trade_count: int
    unleveraged_return_before_fees: Ratio
    live_subscribers: int
    capital: Money | None


def _body(strategy: PublicStrategy) -> PublicStrategyBody:
    listing = strategy.listing
    return PublicStrategyBody(
        id=listing.strategy_id,
        name=listing.name,
        author_name=listing.author_name,
        exchange=listing.exchange,
        venue=listing.venue,
        settlement_currency=listing.settlement_currency,
        created_at=listing.created_at,
        closed_trade_count=strategy.record.closed_trade_count,
        unleveraged_return_before_fees=strategy.record.total_return,
        live_subscribers=strategy.live_subscribers,
        capital=strategy.capital,
    )


def _reader(source: PublicStrategiesSourcePort) -> ReadPublicStrategies:
    return ReadPublicStrategies(source, brake=get_settings().dry_run)


@router.get("", response_model=list[PublicStrategyBody])
async def list_public_strategies(source: SourceDep) -> list[PublicStrategyBody]:
    return [_body(strategy) for strategy in await _reader(source).read_all()]


@router.get("/{strategy_id}", response_model=PublicStrategyBody)
async def read_public_strategy(strategy_id: UUID, source: SourceDep) -> PublicStrategyBody:
    strategy = await _reader(source).read_one(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    return _body(strategy)

"""``/api/subscriptions``: any signed-in user's own subscriptions.

Authentication is attached to the ROUTER, as in ``accounts/infrastructure/
pools_router.py``: the guard is `current_user`, not `require_admin`, because every
route here answers the signed-in user's OWN rows (multi-user design AD8, owner
decision 16). The use cases take that user's id on every call and the repository
filters by it, so another user's subscription is a 404 on every route.

Refusals follow the strategies router: a 404 carries a plain ``detail`` string,
and a 409 carries ``{"error": <CODE>, "message": ...}``.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.wire import Money
from strategy_manager.strategies.domain.strategy import AllocationPercent
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.share_input import Share
from strategy_manager.subscriptions.application.change_share import ChangeShare
from strategy_manager.subscriptions.application.errors import (
    AlreadySubscribed,
    NoPoolForMarket,
    StrategyArchived,
    StrategyNotFound,
    SubscriptionNotActive,
    SubscriptionNotFound,
)
from strategy_manager.subscriptions.application.leave import Leave
from strategy_manager.subscriptions.application.list_subscriptions import ListSubscriptions
from strategy_manager.subscriptions.application.subscribe import Subscribe
from strategy_manager.subscriptions.domain.subscription import Subscription
from strategy_manager.subscriptions.infrastructure.adapters import (
    OpenAllocationAdapter,
    SqlAlchemyStrategyLookup,
    SqlAlchemyUserPools,
)
from strategy_manager.subscriptions.infrastructure.repository import (
    SqlAlchemySubscriptionRepository,
)

router = APIRouter(
    prefix="/subscriptions",
    tags=["subscriptions"],
    dependencies=[Depends(current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUserDep = Annotated[User, Depends(current_user)]


class SubscribeRequest(BaseModel):
    strategy_id: UUID
    allocation_percent: Share


class ChangeShareRequest(BaseModel):
    allocation_percent: Share


class SubscriptionView(BaseModel):
    """What a subscription looks like from outside: the user's own place in a
    strategy, in their own pool."""

    id: UUID
    strategy_id: UUID
    pool_id: int
    allocation_percent: Money
    status: str
    created_at: datetime | None
    left_at: datetime | None
    ended_at: datetime | None

    @classmethod
    def of(cls, subscription: Subscription) -> "SubscriptionView":
        return cls(
            id=subscription.id,
            strategy_id=subscription.strategy_id,
            pool_id=subscription.pool_id,
            allocation_percent=subscription.allocation_percent.value,
            status=subscription.status.value,
            created_at=subscription.created_at,
            left_at=subscription.left_at,
            ended_at=subscription.ended_at,
        )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"error": code, "message": message})


@router.post("", response_model=SubscriptionView, status_code=201)
async def subscribe(
    body: SubscribeRequest, session: SessionDep, user: CurrentUserDep
) -> SubscriptionView:
    use_case = Subscribe(
        subscriptions=SqlAlchemySubscriptionRepository(session),
        strategies=SqlAlchemyStrategyLookup(session),
        pools=SqlAlchemyUserPools(session),
        commit=session,
        clock=SystemClock(),
    )
    try:
        subscription = await use_case.subscribe(
            user.id, body.strategy_id, AllocationPercent(body.allocation_percent)
        )
    except StrategyNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StrategyArchived as exc:
        raise _conflict("STRATEGY_ARCHIVED", str(exc)) from exc
    except NoPoolForMarket as exc:
        raise _conflict("NO_POOL_FOR_MARKET", str(exc)) from exc
    except AlreadySubscribed as exc:
        raise _conflict("ALREADY_SUBSCRIBED", str(exc)) from exc
    return SubscriptionView.of(subscription)


@router.get("", response_model=list[SubscriptionView])
async def list_subscriptions(session: SessionDep, user: CurrentUserDep) -> list[SubscriptionView]:
    """The signed-in user's own subscriptions only."""
    subscriptions = await ListSubscriptions(SqlAlchemySubscriptionRepository(session)).list(
        user.id
    )
    return [SubscriptionView.of(subscription) for subscription in subscriptions]


@router.post("/{subscription_id}/leave", response_model=SubscriptionView)
async def leave(
    subscription_id: UUID, session: SessionDep, user: CurrentUserDep
) -> SubscriptionView:
    use_case = Leave(
        subscriptions=SqlAlchemySubscriptionRepository(session),
        strategies=SqlAlchemyStrategyLookup(session),
        allocations=OpenAllocationAdapter(
            session,
            SqlAlchemyLedgerRepository(session),
            ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
        ),
        pool_lock=PoolLockAdapter(session),
        commit=session,
        clock=SystemClock(),
    )
    try:
        subscription = await use_case.leave(user.id, subscription_id)
    except SubscriptionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriptionNotActive as exc:
        raise _conflict("SUBSCRIPTION_NOT_ACTIVE", str(exc)) from exc
    return SubscriptionView.of(subscription)


@router.patch("/{subscription_id}", response_model=SubscriptionView)
async def change_share(
    subscription_id: UUID,
    body: ChangeShareRequest,
    session: SessionDep,
    user: CurrentUserDep,
) -> SubscriptionView:
    use_case = ChangeShare(SqlAlchemySubscriptionRepository(session), commit=session)
    try:
        subscription = await use_case.change(
            user.id, subscription_id, AllocationPercent(body.allocation_percent)
        )
    except SubscriptionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SubscriptionNotActive as exc:
        raise _conflict("SUBSCRIPTION_NOT_ACTIVE", str(exc)) from exc
    return SubscriptionView.of(subscription)

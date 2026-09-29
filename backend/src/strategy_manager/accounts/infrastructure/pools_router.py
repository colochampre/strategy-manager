"""``GET /pools``: each configured pool, with its balance and what is left to
allocate (design.md section 14).

Read-only. Every pool is its own object, in its own settlement currency, and
the body is a plain list: there is no envelope that could carry a total, and no
field that sums two pools, including two on one exchange (CLAUDE.md rule 7).
Money is serialized as JSON strings in plain notation and instants in UTC
(``shared.infrastructure.wire``): ``Decimal("0E-18")`` never reaches a client.

Authentication is attached to the ROUTER, exactly as in
``strategies/infrastructure/router.py``, which explains why it is structural and
why no route below repeats it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.accounts.domain.pool_overview import BalanceView, PoolOverview
from strategy_manager.accounts.infrastructure.pool_overview import SqlAlchemyPoolOverview
from strategy_manager.shared.config import get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.wire import Instant, Money

router = APIRouter(
    prefix="/pools",
    tags=["pools"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class BalanceBody(BaseModel):
    total: Money
    available: Money
    observed_at: Instant
    stale: bool

    @classmethod
    def of(cls, balance: BalanceView) -> "BalanceBody":
        return cls(
            total=balance.total,
            available=balance.available,
            observed_at=balance.observed_at,
            stale=balance.stale,
        )


class PoolBody(BaseModel):
    """``balance`` and ``allocatable`` are null for a pool nothing has synced."""

    exchange: str
    venue: str
    settlement_currency: str
    enabled: bool
    balance: BalanceBody | None
    reserved: Money
    allocatable: Money | None

    @classmethod
    def of(cls, pool: PoolOverview) -> "PoolBody":
        return cls(
            exchange=pool.exchange,
            venue=pool.venue,
            settlement_currency=pool.settlement_currency,
            enabled=pool.enabled,
            balance=None if pool.balance is None else BalanceBody.of(pool.balance),
            reserved=pool.reserved,
            allocatable=pool.allocatable,
        )


@router.get("", response_model=list[PoolBody])
async def list_pools(session: SessionDep) -> list[PoolBody]:
    overview = SqlAlchemyPoolOverview(
        session,
        SystemClock(),
        snapshot_max_age_seconds=get_settings().balance_snapshot_max_age_seconds,
    )
    return [PoolBody.of(pool) for pool in await overview.list_pools()]

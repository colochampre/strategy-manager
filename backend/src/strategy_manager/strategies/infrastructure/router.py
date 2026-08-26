"""``/strategies`` — registering what this system will act on, and arming it.

Nothing here executes a trade or touches an exchange. It writes configuration
rows, and the worker reads them.

**Two things about this surface are deliberate and will look like omissions.**

There is no ``POST`` body field for ``enabled``: a newly registered strategy
is always off. Registering answers "is this configured correctly?" and arming
answers "should this trade now?", and only the second one moves money. They
are separate calls so that neither can be done by accident while doing the
other.

There is no way to change ``venue`` or ``settlement_currency`` after
registration. That is the guard, not a gap — ``UpdateStrategy`` explains why
at length. In short: it is not an edit, it is a different pool of money, and a
strategy switched between pools routes the close of an open position to the
wrong adapter.

``strategy_id`` is supplied by the caller and is the alert's ``signalType``
UUID. The webhook looks a strategy up under exactly that id, so an id chosen
here rather than copied from the alert would never match anything.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.money import Currency, Venue
from strategy_manager.strategies.application.register_strategy import (
    PoolNotAvailable,
    RegisterCommand,
    RegisterStrategy,
    StrategyAlreadyRegistered,
)
from strategy_manager.strategies.application.update_strategy import (
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.domain.strategy import FillMode, Strategy
from strategy_manager.strategies.infrastructure.pool_catalog import (
    SqlAlchemyPoolCatalog,
)
from strategy_manager.strategies.infrastructure.repository import (
    SqlAlchemyStrategyRepository,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class StrategyView(BaseModel):
    """What a strategy looks like from outside. Deliberately flat: the
    ``policy`` value object is an internal grouping, not an API shape."""

    id: UUID
    name: str
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    allocation_percent: Decimal
    enabled: bool

    @classmethod
    def of(cls, strategy: Strategy) -> "StrategyView":
        return cls(
            id=strategy.id,
            name=strategy.name,
            venue=strategy.policy.venue,
            settlement_currency=strategy.policy.settlement_currency,
            fill_mode=strategy.policy.fill_mode,
            allocation_percent=strategy.policy.allocation_percent.value,
            enabled=strategy.enabled,
        )


class RegisterRequest(BaseModel):
    """``id`` is the alert's ``signalType``. It is required, and there is no
    server-side default, because a generated one would match no alert."""

    id: UUID
    name: str = Field(min_length=1)
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    allocation_percent: Decimal = Field(default=Decimal("100"), gt=0, le=100)


class UpdateRequest(BaseModel):
    """Every field is optional; omitted means unchanged.

    ``venue`` and ``settlement_currency`` are absent on purpose — see this
    module's docstring.
    """

    name: str | None = Field(default=None, min_length=1)
    fill_mode: FillMode | None = None
    allocation_percent: Decimal | None = Field(default=None, gt=0, le=100)
    enabled: bool | None = None


@router.post("", response_model=StrategyView, status_code=201)
async def register_strategy(
    body: RegisterRequest, session: SessionDep
) -> StrategyView:
    use_case = RegisterStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pools=SqlAlchemyPoolCatalog(session),
        commit=session,
    )
    try:
        strategy = await use_case.register(
            RegisterCommand(
                strategy_id=body.id,
                name=body.name,
                venue=body.venue,
                settlement_currency=body.settlement_currency,
                fill_mode=body.fill_mode,
                allocation_percent=body.allocation_percent,
            )
        )
    except StrategyAlreadyRegistered as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PoolNotAvailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        # ``name`` is UNIQUE at the database level. Reported as a conflict
        # rather than a 500, because the caller can fix it by sending another
        # name.
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a strategy named {body.name!r} already exists"
        ) from exc

    return StrategyView.of(strategy)


@router.get("", response_model=list[StrategyView])
async def list_strategies(session: SessionDep) -> list[StrategyView]:
    strategies = await SqlAlchemyStrategyRepository(session).list_all()
    return [StrategyView.of(strategy) for strategy in strategies]


@router.get("/{strategy_id}", response_model=StrategyView)
async def get_strategy(strategy_id: UUID, session: SessionDep) -> StrategyView:
    strategy = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    return StrategyView.of(strategy)


@router.patch("/{strategy_id}", response_model=StrategyView)
async def update_strategy(
    strategy_id: UUID, body: UpdateRequest, session: SessionDep
) -> StrategyView:
    use_case = UpdateStrategy(
        repository=SqlAlchemyStrategyRepository(session), commit=session
    )
    try:
        strategy = await use_case.update(
            UpdateCommand(
                strategy_id=strategy_id,
                name=body.name,
                fill_mode=body.fill_mode,
                allocation_percent=body.allocation_percent,
                enabled=body.enabled,
            )
        )
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a strategy named {body.name!r} already exists"
        ) from exc

    return StrategyView.of(strategy)

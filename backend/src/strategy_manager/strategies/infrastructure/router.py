"""``/strategies`` — registering what this system will act on, and arming it.

Nothing here executes a trade or touches an exchange. It writes configuration
rows, and the worker reads them.

**Two things about this surface are deliberate and will look like omissions.**

There is no ``POST`` body field for ``enabled``: a newly registered strategy
is always off. Registering answers "is this configured correctly?" and arming
answers "should this trade now?", and only the second one moves money. They
are separate calls so that neither can be done by accident while doing the
other.

There is no way to change ``exchange``, ``venue`` or ``settlement_currency``
after registration. That is the guard, not a gap — ``UpdateStrategy`` explains why
at length. In short: it is not an edit, it is a different pool of money, and a
strategy switched between pools routes the close of an open position to the
wrong adapter.

``strategy_id`` is supplied by the caller and is the alert's ``signalType``
UUID. The webhook looks a strategy up under exactly that id, so an id chosen
here rather than copied from the alert would never match anything.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.allocation.infrastructure.repository import (
    SqlAlchemyReservationRepository,
)
from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.ledger.application.read_symbol_holdings import ReadSymbolHoldings
from strategy_manager.ledger.infrastructure.repository import SqlAlchemyLedgerRepository
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.strategies.application.archive_strategy import (
    ArchiveStrategy,
    OpenPosition,
    StillEnabled,
)
from strategy_manager.strategies.application.ports import PairCatalogPort
from strategy_manager.strategies.application.register_strategy import (
    PoolNotAvailable,
    RegisterCommand,
    RegisterStrategy,
    StrategyAlreadyRegistered,
)
from strategy_manager.strategies.application.replace_allowed_pairs import (
    ReplaceAllowedPairs,
    ReplaceAllowedPairsCommand,
)
from strategy_manager.strategies.application.update_strategy import (
    StrategyArchived,
    UnknownStrategy,
    UpdateCommand,
    UpdateStrategy,
)
from strategy_manager.strategies.domain.allowed_pairs import EmptyAllowedPairs
from strategy_manager.strategies.domain.enablement import EnablementEvent, Uptime, uptime
from strategy_manager.strategies.domain.pair_catalog import (
    PairCatalogNotServed,
    PairCatalogUnavailable,
    PairsChangedConcurrently,
    UnknownPairs,
)
from strategy_manager.strategies.domain.strategy import FillMode, Strategy
from strategy_manager.strategies.infrastructure.enablement_log import (
    SqlAlchemyEnablementLog,
)
from strategy_manager.strategies.infrastructure.exposure_adapter import (
    StrategyExposureAdapter,
)
from strategy_manager.strategies.infrastructure.pair_catalog_router import get_pair_catalog
from strategy_manager.strategies.infrastructure.pool_catalog import (
    SqlAlchemyPoolCatalog,
)
from strategy_manager.strategies.infrastructure.pool_lock_adapter import PoolLockAdapter
from strategy_manager.strategies.infrastructure.repository import (
    SqlAlchemyStrategyRepository,
)

# Authentication is attached to the ROUTER, so it applies to every route
# declared below AND to every route anyone adds after this line — without the
# author of that route doing, knowing or remembering anything. The protection
# is structural, not a checklist item.
#
# That distinction is the whole point. Per-endpoint dependencies protect the
# endpoints someone remembered, and this file is a place where endpoints get
# added: the next one added in a hurry is precisely the one that would ship
# open, and it would look exactly like the four already here. A decorator that
# has to be copied is a rule that will eventually not be.
#
# So there is deliberately no ``Depends(require_admin_token)`` on any route
# below. Adding one would not be harmless duplication — it would teach the
# next reader that this is where authentication lives, and the route that then
# omits it inherits nothing and says nothing.
router = APIRouter(
    prefix="/strategies",
    tags=["strategies"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class UptimeView(BaseModel):
    """Mirrors ``enablement.Uptime`` (design.md § 9). ``baseline=True``
    means the earliest known enable is a BASELINE row written by migration
    0024 -- the true first-enabled date is unknown, and the panel renders
    "active >= X days" rather than claiming an exact one."""

    seconds: float
    first_enabled_at: datetime | None
    baseline: bool

    @classmethod
    def of(cls, value: Uptime) -> "UptimeView":
        return cls(
            seconds=value.seconds, first_enabled_at=value.first_enabled_at, baseline=value.baseline
        )


class StrategyView(BaseModel):
    """What a strategy looks like from outside. Deliberately flat: the
    ``policy`` value object is an internal grouping, not an API shape."""

    id: UUID
    name: str
    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    allocation_percent: Decimal
    enabled: bool
    archived_at: datetime | None
    allowed_pairs: list[str]
    uptime: UptimeView

    @classmethod
    def of(cls, strategy: Strategy, uptime_value: Uptime) -> "StrategyView":
        return cls(
            id=strategy.id,
            name=strategy.name,
            exchange=strategy.policy.exchange,
            venue=strategy.policy.venue,
            settlement_currency=strategy.policy.settlement_currency,
            fill_mode=strategy.policy.fill_mode,
            allocation_percent=strategy.policy.allocation_percent.value,
            enabled=strategy.enabled,
            archived_at=strategy.archived_at,
            allowed_pairs=strategy.allowed_pairs.sorted(),
            uptime=UptimeView.of(uptime_value),
        )


class EnablementEventView(BaseModel):
    """One row of ``GET /strategies/{id}/events`` (design.md § 14)."""

    enabled: bool
    occurred_at: datetime
    origin: str

    @classmethod
    def of(cls, event: EnablementEvent) -> "EnablementEventView":
        return cls(enabled=event.enabled, occurred_at=event.occurred_at, origin=event.origin.value)


class RegisterRequest(BaseModel):
    """``id`` is the alert's ``signalType``. It is required, and there is no
    server-side default, because a generated one would match no alert."""

    id: UUID
    name: str = Field(min_length=1)
    exchange: Exchange
    venue: Venue
    settlement_currency: Currency
    fill_mode: FillMode
    allocation_percent: Decimal = Field(default=Decimal("100"), gt=0, le=100)
    allowed_pairs: list[str] = Field(min_length=1)


class UpdateRequest(BaseModel):
    """Every field is optional; omitted means unchanged.

    ``exchange``, ``venue`` and ``settlement_currency`` are absent on purpose
    — see this module's docstring.
    """

    name: str | None = Field(default=None, min_length=1)
    fill_mode: FillMode | None = None
    allocation_percent: Decimal | None = Field(default=None, gt=0, le=100)
    enabled: bool | None = None


class ReplacePairsRequest(BaseModel):
    """``PUT /strategies/{id}/allowed-pairs`` -- the panel sends the
    COMPLETE list it wants; this replaces the whole column, never merges
    (design.md § 6)."""

    pairs: list[str] = Field(min_length=1)


PairCatalogDep = Annotated[PairCatalogPort, Depends(get_pair_catalog)]

# The error codes the panel decides on (design addendum § E). The body carries its
# own code, so a client never depends on the status alone.
UNKNOWN_PAIRS = "UNKNOWN_PAIRS"
PAIR_CATALOGUE_UNAVAILABLE = "PAIR_CATALOGUE_UNAVAILABLE"
PAIR_CATALOGUE_NOT_SERVED = "PAIR_CATALOGUE_NOT_SERVED"
PAIRS_CHANGED = "PAIRS_CHANGED"


def _pair_refusal(
    exc: UnknownPairs | PairCatalogNotServed | PairCatalogUnavailable | PairsChangedConcurrently,
) -> HTTPException:
    """The HTTP form of the four pair-catalogue refusals, shared by POST and PUT.

    The use case already logged one WARNING for each, so nothing is logged here.
    No venue payload, URL or credential is in any body: only the symbols the
    caller itself sent, normalized.
    """
    if isinstance(exc, UnknownPairs):
        # The input is the problem: the symbols are named, sorted.
        return HTTPException(
            status_code=422,
            detail={"error": UNKNOWN_PAIRS, "message": str(exc), "unknown": list(exc.unknown)},
        )
    if isinstance(exc, PairCatalogNotServed):
        # The request names a pool this system cannot validate pairs for.
        return HTTPException(
            status_code=422,
            detail={
                "error": PAIR_CATALOGUE_NOT_SERVED,
                "message": "pairs cannot be checked for this pool: no catalogue is served for it",
            },
        )
    if isinstance(exc, PairCatalogUnavailable):
        # The upstream venue failed: 502, not 422 (the operator's input was fine).
        return HTTPException(
            status_code=502,
            detail={
                "error": PAIR_CATALOGUE_UNAVAILABLE,
                "message": "the exchange's pair list could not be read, so nothing was saved; "
                "try again",
            },
        )
    # PairsChangedConcurrently: a well-formed request whose target changed under it.
    return HTTPException(status_code=409, detail={"error": PAIRS_CHANGED, "message": str(exc)})


def get_register_strategy(session: SessionDep, pairs: PairCatalogDep) -> RegisterStrategy:
    """The real wiring. The catalogue comes from ``get_pair_catalog``, so a test
    overrides ONE dependency and no router test reaches a venue."""
    return RegisterStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pools=SqlAlchemyPoolCatalog(session),
        pairs=pairs,
        commit=session,
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
    )


def get_replace_allowed_pairs(session: SessionDep, pairs: PairCatalogDep) -> ReplaceAllowedPairs:
    return ReplaceAllowedPairs(
        repository=SqlAlchemyStrategyRepository(session), pairs=pairs, commit=session
    )


@router.post("", response_model=StrategyView, status_code=201)
async def register_strategy(
    body: RegisterRequest,
    session: SessionDep,
    use_case: Annotated[RegisterStrategy, Depends(get_register_strategy)],
) -> StrategyView:
    try:
        strategy = await use_case.register(
            RegisterCommand(
                strategy_id=body.id,
                name=body.name,
                exchange=body.exchange,
                venue=body.venue,
                settlement_currency=body.settlement_currency,
                fill_mode=body.fill_mode,
                allocation_percent=body.allocation_percent,
                allowed_pairs=body.allowed_pairs,
            )
        )
    except StrategyAlreadyRegistered as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PoolNotAvailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EmptyAllowedPairs as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (UnknownPairs, PairCatalogNotServed, PairCatalogUnavailable) as exc:
        raise _pair_refusal(exc) from exc
    except IntegrityError as exc:
        # ``name`` is UNIQUE at the database level. Reported as a conflict
        # rather than a 500, because the caller can fix it by sending another
        # name.
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a strategy named {body.name!r} already exists"
        ) from exc

    # A just-created strategy has zero events by construction (creation
    # writes no event, F8) -- no query needed for its uptime.
    return StrategyView.of(strategy, uptime([], datetime.now(UTC)))


@router.get("", response_model=list[StrategyView])
async def list_strategies(
    session: SessionDep, include_archived: bool = False
) -> list[StrategyView]:
    strategies = await SqlAlchemyStrategyRepository(session).list_all(
        include_archived=include_archived
    )
    # ONE query for every strategy's events (design.md § 14:
    # "list_all(include_archived) + one events query -> uptime()"), not one
    # per strategy -- acceptable either way at today's scale (tens of
    # strategies), but this is the bulk form.
    events_by_strategy = await SqlAlchemyEnablementLog(session).list_for_many(
        [strategy.id for strategy in strategies]
    )
    now = datetime.now(UTC)
    return [
        StrategyView.of(
            strategy, uptime(events_by_strategy.get(strategy.id, []), now)
        )
        for strategy in strategies
    ]


@router.get("/{strategy_id}", response_model=StrategyView)
async def get_strategy(strategy_id: UUID, session: SessionDep) -> StrategyView:
    strategy = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return StrategyView.of(strategy, uptime(events, datetime.now(UTC)))


@router.get("/{strategy_id}/events", response_model=list[EnablementEventView])
async def get_strategy_events(
    strategy_id: UUID, session: SessionDep
) -> list[EnablementEventView]:
    strategy = await SqlAlchemyStrategyRepository(session).get_by_id(strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="no such strategy")
    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return [EnablementEventView.of(event) for event in events]


@router.put("/{strategy_id}/allowed-pairs", response_model=StrategyView)
async def replace_allowed_pairs(
    strategy_id: UUID,
    body: ReplacePairsRequest,
    session: SessionDep,
    use_case: Annotated[ReplaceAllowedPairs, Depends(get_replace_allowed_pairs)],
) -> StrategyView:
    try:
        strategy = await use_case.replace(
            ReplaceAllowedPairsCommand(strategy_id=strategy_id, pairs=body.pairs)
        )
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StrategyArchived as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_ARCHIVED", "message": str(exc)}
        ) from exc
    except EmptyAllowedPairs as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (
        UnknownPairs,
        PairCatalogNotServed,
        PairCatalogUnavailable,
        PairsChangedConcurrently,
    ) as exc:
        raise _pair_refusal(exc) from exc

    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return StrategyView.of(strategy, uptime(events, datetime.now(UTC)))


@router.patch("/{strategy_id}", response_model=StrategyView)
async def update_strategy(
    strategy_id: UUID, body: UpdateRequest, session: SessionDep
) -> StrategyView:
    use_case = UpdateStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        commit=session,
        enablement_log=SqlAlchemyEnablementLog(session),
        clock=SystemClock(),
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
    except StrategyArchived as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STRATEGY_ARCHIVED", "message": str(exc)}
        ) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a strategy named {body.name!r} already exists"
        ) from exc

    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return StrategyView.of(strategy, uptime(events, datetime.now(UTC)))


@router.post("/{strategy_id}/archive", response_model=StrategyView)
async def archive_strategy(strategy_id: UUID, session: SessionDep) -> StrategyView:
    """Decision 14: archive only a disabled, flat strategy. Idempotent --
    calling this again on an already-archived strategy answers 200 with the
    SAME ``archived_at``, never a fresh one (design.md § 8's sequence
    diagram; design.md's API table)."""
    use_case = ArchiveStrategy(
        repository=SqlAlchemyStrategyRepository(session),
        pool_lock=PoolLockAdapter(session),
        exposure=StrategyExposureAdapter(
            ledger=SqlAlchemyLedgerRepository(session),
            symbol_holdings=ReadSymbolHoldings(SqlAlchemyLedgerRepository(session)),
            reservations=SqlAlchemyReservationRepository(session),
            attempts=SqlAlchemyExecutionAttemptRepository(session),
        ),
        commit=session,
        clock=SystemClock(),
    )
    try:
        result = await use_case.archive(strategy_id)
    except UnknownStrategy as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StillEnabled as exc:
        raise HTTPException(
            status_code=409, detail={"error": "STILL_ENABLED", "message": str(exc)}
        ) from exc
    except OpenPosition as exc:
        # ``HTTPException.detail`` is serialized by Starlette's plain
        # ``json.dumps``, not ``jsonable_encoder`` -- a raw ``UUID`` in the
        # dict raises ``TypeError`` at response-render time, well after this
        # handler returns, so every id is stringified explicitly here.
        raise HTTPException(
            status_code=409,
            detail={
                "error": "OPEN_POSITION",
                "message": str(exc),
                "symbols": sorted(exc.exposure.symbols),
                "allocations": [str(a) for a in exc.exposure.allocations],
                "live_reservations": [str(r) for r in exc.exposure.live_reservations],
                "in_flight_attempts": [str(a) for a in exc.exposure.in_flight_attempts],
            },
        ) from exc

    events = await SqlAlchemyEnablementLog(session).list_for(strategy_id)
    return StrategyView.of(result.strategy, uptime(events, datetime.now(UTC)))

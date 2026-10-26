"""``GET /api/positions/open``: every open position and every in-flight order of
the system (design addendum "open positions", decision 65, section F).

One route, no parameter, for the whole system: each element carries its own pool
and its own currency, and no field adds two of them (CLAUDE.md rule 7). Nothing
here decides that a row exists; ``ReadOpenPositions`` iterates the mode guard's
own reader (``SqlAlchemyModeOriginReader``, given to it exactly as the worker's
start gives it to the guard). This module only builds the wire.

**One snapshot.** Every source the use case is given, the guard's reader, the
facts and the disagreements, is built on the SAME session, the one
``get_snapshot_session`` opens as a read-only ``REPEATABLE READ`` transaction.
A source built on any other session would read another state.

The route writes nothing, takes no lock a writer waits on, needs no credential
and returns none. A read that fails is a 500 with the usual trace (the panel
shows its error state, never an empty list). Authentication is attached to the
ROUTER, as on every admin router.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.mode_origin_reader import (
    SqlAlchemyModeOriginReader,
)
from strategy_manager.identity.domain.user import User
from strategy_manager.identity.infrastructure.dependencies import current_user, require_admin
from strategy_manager.performance.application.ports import (
    ConfirmedDisagreementSourcePort,
    OpenPositionFactsSourcePort,
    OpenStateSourcePort,
)
from strategy_manager.performance.application.read_open_positions import ReadOpenPositions
from strategy_manager.performance.domain.open_position import (
    InFlightOrder,
    OpenPosition,
    PoolLabel,
)
from strategy_manager.performance.infrastructure.confirmed_disagreement_source import (
    ConfirmedDisagreementSource,
)
from strategy_manager.performance.infrastructure.open_position_facts_source import (
    SqlAlchemyOpenPositionFactsSource,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.wire import Instant, Money, Price

router = APIRouter(
    prefix="/positions",
    tags=["positions"],
    dependencies=[Depends(require_admin)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_snapshot_session(
    session: SessionDep, user: Annotated[User, Depends(current_user)]
) -> AsyncIterator[AsyncSession]:
    """The session of ONE request, in a read-only ``REPEATABLE READ`` transaction.

    The statement must be the transaction's FIRST: PostgreSQL refuses to change
    the isolation level after a query ("must be called before any query"), and
    that refusal propagates as a 500 and the panel's error state. A snapshot that
    is not in force is never silently dropped (design K row 15). The use case and
    the ports know nothing of this.

    ``user`` is a parameter only for its ORDER: ``current_user`` resolves the
    signed-in user, which may INSERT the row of a first-time user, and commits it
    before the route runs. That must happen before this transaction starts, or
    the insert is refused (read only) and the isolation statement is no longer
    first. FastAPI runs a dependency once per request, so the route's own
    ``current_user`` is this very result."""
    del user
    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    yield session


SnapshotSessionDep = Annotated[AsyncSession, Depends(get_snapshot_session)]


def get_open_state_source(session: SnapshotSessionDep) -> OpenStateSourcePort:
    return SqlAlchemyModeOriginReader(session)


def get_facts_source(session: SnapshotSessionDep) -> OpenPositionFactsSourcePort:
    return SqlAlchemyOpenPositionFactsSource(session)


def get_disagreement_source(session: SnapshotSessionDep) -> ConfirmedDisagreementSourcePort:
    return ConfirmedDisagreementSource(SqlAlchemyDiscrepancyRepository(session))


def get_clock() -> ClockPort:
    return SystemClock()


OpenStateDep = Annotated[OpenStateSourcePort, Depends(get_open_state_source)]
FactsDep = Annotated[OpenPositionFactsSourcePort, Depends(get_facts_source)]
DisagreementDep = Annotated[ConfirmedDisagreementSourcePort, Depends(get_disagreement_source)]
ClockDep = Annotated[ClockPort, Depends(get_clock)]


class PoolBody(BaseModel):
    exchange: str
    venue: str
    settlement_currency: str


class FeeBody(BaseModel):
    currency: str
    amount: Money


class VenueDisagreementBody(BaseModel):
    discrepancy_id: UUID
    venue_net_base: Money
    ledger_net_base: Money
    allocation_count: int
    last_observed_at: Instant


class PositionBody(BaseModel):
    allocation_id: UUID
    strategy_id: UUID | None
    strategy_name: str
    strategy_archived: bool | None
    pool: PoolBody
    currency: str
    markets: list[str]
    origin: str
    figures_missing: str | None
    side: str | None
    base_currency: str | None
    size: Money | None
    opened_size: Money | None
    entry_price: Price | None
    opened_at: Instant | None
    fill_count: int
    fees: Money | None
    other_fees: list[FeeBody]
    margin_granted: Money | None
    leverage: Money | None
    reservation_status: str | None
    venue_disagreement: VenueDisagreementBody | None


class OrderBody(BaseModel):
    attempt_id: UUID
    strategy_id: UUID | None
    strategy_archived: bool | None
    strategy_name: str | None
    pool: PoolBody
    market: str
    action: str | None
    origin: str
    submitted_at: Instant | None


class OpenPositionsBody(BaseModel):
    as_of: Instant
    positions: list[PositionBody]
    orders: list[OrderBody]


def _pool(pool: PoolLabel) -> PoolBody:
    return PoolBody(
        exchange=pool.exchange, venue=pool.venue, settlement_currency=pool.settlement_currency
    )


def _position_body(position: OpenPosition) -> PositionBody:
    figures = position.figures
    missing = position.figures_missing
    mark = position.venue_disagreement
    return PositionBody(
        allocation_id=position.allocation_id,
        strategy_id=position.strategy_id,
        strategy_name=position.strategy_name,
        strategy_archived=position.strategy_archived,
        pool=_pool(position.pool),
        currency=position.pool.settlement_currency,
        markets=list(position.markets),
        origin=position.origin.value,
        figures_missing=None if missing is None else missing.value,
        side=None if figures is None else figures.side.value,
        base_currency=None if figures is None else figures.base_currency,
        size=None if figures is None else figures.size,
        opened_size=None if figures is None else figures.opened_size,
        entry_price=None if figures is None else figures.entry_price,
        opened_at=position.opened_at,
        fill_count=position.fill_count,
        fees=position.fees,
        other_fees=[FeeBody(currency=f.currency, amount=f.amount) for f in position.other_fees],
        margin_granted=position.margin_granted,
        leverage=position.leverage,
        reservation_status=position.reservation_status,
        venue_disagreement=(
            None
            if mark is None
            else VenueDisagreementBody(
                discrepancy_id=mark.discrepancy_id,
                venue_net_base=mark.venue_net_base,
                ledger_net_base=mark.ledger_net_base,
                allocation_count=mark.allocation_count,
                last_observed_at=mark.last_observed_at,
            )
        ),
    )


def _order_body(order: InFlightOrder) -> OrderBody:
    return OrderBody(
        attempt_id=order.attempt_id,
        strategy_id=order.strategy_id,
        strategy_archived=order.strategy_archived,
        strategy_name=order.strategy_name,
        pool=_pool(order.pool),
        market=order.market,
        action=None if order.action is None else order.action.value,
        origin=order.origin.value,
        submitted_at=order.submitted_at,
    )


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _position_order(position: OpenPosition) -> tuple[str, str, str, str, tuple[str, ...], str]:
    """Strategy name, pool, market, allocation id (design section F)."""
    pool = position.pool
    return (
        position.strategy_name,
        pool.exchange,
        pool.venue,
        pool.settlement_currency,
        position.markets,
        str(position.allocation_id),
    )


def _order_order(order: InFlightOrder) -> tuple[bool, datetime, str]:
    """``submitted_at``, then the attempt id. An order whose time is unknown (the
    facts could not decorate it) sorts LAST; two of them are told apart by the
    attempt id, so the order does not depend on the order the rows arrive in."""
    submitted = order.submitted_at
    return (submitted is None, _EPOCH if submitted is None else submitted, str(order.attempt_id))


@router.get("/open", response_model=OpenPositionsBody)
async def read_open_positions(
    state: OpenStateDep,
    facts: FactsDep,
    disagreements: DisagreementDep,
    clock: ClockDep,
    user: Annotated[User, Depends(current_user)],
) -> OpenPositionsBody:
    # The instant of the snapshot: taken before the first read, after the
    # snapshot dependency has opened the transaction.
    as_of = clock.now()
    answer = await ReadOpenPositions(state, facts, disagreements).read(user.id)
    return OpenPositionsBody(
        as_of=as_of,
        positions=[_position_body(p) for p in sorted(answer.positions, key=_position_order)],
        orders=[_order_body(o) for o in sorted(answer.orders, key=_order_order)],
    )

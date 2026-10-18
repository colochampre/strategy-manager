"""``/reconciliation`` -- read-only visibility into what a scan found
disagreeing between a venue's own reported net position and the ledger's.

Two routes, both reads: ``GET /discrepancies`` and ``GET /confirmed``. Nothing
here writes, resolves or acts on a discrepancy: booking is automatic and runs
in the worker (owner decision 66 Q1, 2026-10-16), so the approve and reject
routes this module once served are gone. Auth is on the ROUTER, not on the
single routes below, following the exact rule
``strategies/infrastructure/router.py`` documents at length: the protection
must be structural, because the next route someone adds here in a hurry is
precisely the one that would ship unprotected if authentication were a
decorator to remember instead.

**Two "status" concepts share a name and mean different things.** This
endpoint's own ``status`` QUERY parameter (``open``/``resolved``/``all``)
filters on ``resolved_at`` -- whether an operator has closed the record out.
The response body's ``status`` FIELD is the domain lifecycle value
(``OBSERVED``/``CONFIRMED``, see ``DiscrepancyStatus``) -- whether a scan has
seen the disagreement enough consecutive times to trust it. A row can be
``CONFIRMED`` and still open, or ``OBSERVED`` and already resolved; the two
axes are independent. See ``reconciliation.domain.discrepancy`` and migration
``0020`` for why.

Reuses ``DiscrepancyRepositoryPort.list_discrepancies`` exactly as Unit 1
left it (``pool``, ``status``, ``open_only``) rather than growing its
contract: filtering by exchange/venue/settlement_currency/symbol and applying
``limit`` in Python, after the one DB round trip ``open_only`` already
narrows, costs nothing worth a wider port for.

**Where that assumption breaks.** It holds for the default ``open`` filter,
which ``open_only`` narrows through the partial index and which stays small
by construction -- one row per disagreeing pool+symbol. It does NOT hold
forever for ``resolved`` or ``all``: resolving preserves history rather than
deleting it (migration ``0020``, design decision 5), so those two read every
row the table has ever held and discard most of them in Python, and ``limit``
bounds the response without bounding the query. That is fine at this table's
real size and wrong at some larger one. The fix, when it is needed, is to
push ``limit`` and the pool/symbol filters into the port as real SQL -- not
to paginate in Python on top of a full read.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.reconciliation.application.market_key import market_key
from strategy_manager.reconciliation.application.ports import DiscrepancyRecord
from strategy_manager.reconciliation.application.read_confirmed import (
    ConfirmedDiscrepancy,
    ReadConfirmed,
)
from strategy_manager.reconciliation.domain.attention import NeedsOwnerReason
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.reconciliation.infrastructure.strategy_name_adapter import (
    StrategyNameAdapter,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.wire import Money, plain

# See this module's docstring and ``strategies/infrastructure/router.py``:
# deliberately no ``Depends(require_admin_token)`` on the route itself.
router = APIRouter(
    prefix="/reconciliation",
    tags=["reconciliation"],
    dependencies=[Depends(require_admin_token)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: The endpoint's own resolution filter. Deliberately NOT ``DiscrepancyStatus``
#: -- see the module docstring.
ResolutionFilter = Literal["open", "resolved", "all"]


class DiscrepancyView(BaseModel):
    """One ``reconciliation_discrepancies`` row, as read back by an operator.

    ``status`` is the domain lifecycle value (``OBSERVED``/``CONFIRMED``),
    not this endpoint's own ``status`` query parameter -- see the module
    docstring.

    ``confirmed_at`` means "first confirmed at", not "is confirmed now": it
    survives a demotion back to ``OBSERVED`` (migration ``0020``). Read
    ``status`` to know whether a row is confirmed NOW.
    """

    id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    venue_net_base: Money
    ledger_net_base: Money
    open_allocation_ids: tuple[UUID, ...]
    consecutive_scans: int
    status: DiscrepancyStatus
    first_observed_at: datetime
    last_observed_at: datetime
    confirmed_at: datetime | None
    resolved_at: datetime | None

    @classmethod
    def of(cls, record: DiscrepancyRecord) -> "DiscrepancyView":
        return cls(
            id=record.id,
            exchange=record.exchange,
            venue=record.venue,
            settlement_currency=record.settlement_currency,
            symbol=record.symbol,
            kind=record.kind,
            venue_net_base=record.venue_net_base,
            ledger_net_base=record.ledger_net_base,
            open_allocation_ids=record.open_allocation_ids,
            consecutive_scans=record.consecutive_scans,
            status=record.status,
            first_observed_at=record.first_observed_at,
            last_observed_at=record.last_observed_at,
            confirmed_at=record.confirmed_at,
            resolved_at=record.resolved_at,
        )


@router.get("/discrepancies", response_model=list[DiscrepancyView])
async def list_discrepancies(
    session: SessionDep,
    resolution: Annotated[ResolutionFilter, Query(alias="status")] = "open",
    exchange: str | None = None,
    venue: str | None = None,
    settlement_currency: str | None = None,
    symbol: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DiscrepancyView]:
    repository = SqlAlchemyDiscrepancyRepository(session)
    # ``open_only`` is the one case the port already narrows at the DB level
    # -- it is also the default, so the common call stays a single indexed
    # read. ``resolved`` has no port-level mirror (see module docstring), so
    # it is filtered below, on the already-small result set.
    records = await repository.list_discrepancies(open_only=resolution == "open")

    if resolution == "resolved":
        records = [record for record in records if record.resolved_at is not None]
    if exchange is not None:
        records = [record for record in records if record.exchange == exchange]
    if venue is not None:
        records = [record for record in records if record.venue == venue]
    if settlement_currency is not None:
        records = [
            record
            for record in records
            if record.settlement_currency == settlement_currency
        ]
    if symbol is not None:
        # The scan stores the market key (``STXUSDT``), while an operator
        # reading a TradingView alert types ``STXUSDT.P``. Both sides are
        # normalised, so either spelling finds the row -- including a row
        # written under a marker spelling before keys were canonical.
        wanted = market_key(symbol)
        records = [record for record in records if market_key(record.symbol) == wanted]

    return [DiscrepancyView.of(record) for record in records[:limit]]


class AllocationBody(BaseModel):
    allocation_id: UUID
    strategy_id: UUID | None
    strategy_name: str | None


class ConfirmedDiscrepancyBody(BaseModel):
    discrepancy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    reason: NeedsOwnerReason | None
    venue_net_base: str
    ledger_net_base: str
    allocations: list[AllocationBody]
    confirmed_at: datetime | None
    last_observed_at: datetime


class BookedBody(BaseModel):
    proposal_id: UUID
    discrepancy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    strategy_id: UUID
    strategy_name: str | None
    allocation_id: UUID
    side: str
    quantity: str
    fill_count: int
    decided_at: datetime
    decided_by: Literal["automatic", "owner"]
    execution_attempt_id: UUID | None
    discrepancy_open: bool


class ConfirmedBody(BaseModel):
    """``GET /reconciliation/confirmed`` (design PR 15 addendum § G). Every
    quantity is typed ``str`` on purpose, never ``Decimal``: FastAPI's default
    ``Decimal`` encoder turns a fractional value into a ``float`` on the wire,
    which silently loses precision an append-only ledger depends on."""

    read_at: datetime
    dry_run: bool
    needs_owner_count: int
    needs_owner: list[ConfirmedDiscrepancyBody]
    being_booked: list[ConfirmedDiscrepancyBody]
    booked: list[BookedBody]


def _discrepancy_body(item: ConfirmedDiscrepancy) -> ConfirmedDiscrepancyBody:
    return ConfirmedDiscrepancyBody(
        discrepancy_id=item.discrepancy_id,
        exchange=item.exchange,
        venue=item.venue,
        settlement_currency=item.settlement_currency,
        symbol=item.symbol,
        kind=item.kind,
        reason=item.reason,
        venue_net_base=plain(item.venue_net_base),
        ledger_net_base=plain(item.ledger_net_base),
        allocations=[
            AllocationBody(
                allocation_id=a.allocation_id,
                strategy_id=a.strategy_id,
                strategy_name=a.strategy_name,
            )
            for a in item.allocations
        ],
        confirmed_at=item.confirmed_at,
        last_observed_at=item.last_observed_at,
    )


@router.get("/confirmed", response_model=ConfirmedBody)
async def read_confirmed(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> ConfirmedBody:
    """Read-only, whole-system, no parameter (owner decision 66 Q6). Serves
    what the database holds with ``dry_run`` beside it (note N3); the panel
    decides what to draw under ``DRY_RUN``."""

    reading = await ReadConfirmed(
        discrepancies=SqlAlchemyDiscrepancyRepository(session),
        proposals=SqlAlchemyBookingProposalRepository(session),
        names=StrategyNameAdapter(session),
        clock=SystemClock(),
        grace_seconds=settings.reconciliation_auto_booking_grace_seconds,
        dry_run=settings.dry_run,
    ).read()
    return ConfirmedBody(
        read_at=reading.read_at,
        dry_run=reading.dry_run,
        needs_owner_count=reading.needs_owner_count,
        needs_owner=[_discrepancy_body(i) for i in reading.needs_owner],
        being_booked=[_discrepancy_body(i) for i in reading.being_booked],
        booked=[
            BookedBody(
                proposal_id=b.proposal_id,
                discrepancy_id=b.discrepancy_id,
                exchange=b.exchange,
                venue=b.venue,
                settlement_currency=b.settlement_currency,
                symbol=b.symbol,
                kind=b.kind,
                strategy_id=b.strategy_id,
                strategy_name=b.strategy_name,
                allocation_id=b.allocation_id,
                side=b.side,
                quantity=plain(b.quantity),
                fill_count=b.fill_count,
                decided_at=b.decided_at,
                decided_by=b.decided_by,
                execution_attempt_id=b.execution_attempt_id,
                discrepancy_open=b.discrepancy_open,
            )
            for b in reading.booked
        ],
    )

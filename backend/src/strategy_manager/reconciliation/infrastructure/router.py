"""``/reconciliation`` -- read-only visibility into what a scan found
disagreeing between a venue's own reported net position and the ledger's.

Slice 1 has exactly one route: nothing here writes, resolves or acts on a
discrepancy. Auth is on the ROUTER, not on the single route below, following
the exact rule ``strategies/infrastructure/router.py`` documents at length:
the protection must be structural, because the next route someone adds here
in a hurry is precisely the one that would ship unprotected if authentication
were a decorator to remember instead.

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

import logging
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.execution.infrastructure.repository import (
    SqlAlchemyExecutionAttemptRepository,
)
from strategy_manager.reconciliation.application.approve_booking import (
    ApproveBooking,
    ApproveOutcome,
    ApproveResult,
)
from strategy_manager.reconciliation.application.market_key import market_key
from strategy_manager.reconciliation.application.ports import (
    BookingProposalNotFound,
    BookingProposalRecord,
    DiscrepancyRecord,
    ProposedFillSnapshot,
)
from strategy_manager.reconciliation.application.reject_booking import RejectBooking, RejectOutcome
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
)
from strategy_manager.reconciliation.infrastructure.booking_proposal_repository import (
    SqlAlchemyBookingProposalRepository,
)
from strategy_manager.reconciliation.infrastructure.booking_writer import SqlAlchemyBookingWriter
from strategy_manager.reconciliation.infrastructure.in_flight_close_adapter import (
    InFlightCloseAdapter,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.shared.config import Settings, get_settings
from strategy_manager.shared.db import get_session
from strategy_manager.shared.domain.money import Currency
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token
from strategy_manager.shared.infrastructure.clock import SystemClock
from strategy_manager.shared.infrastructure.usd_rate import FixedUsdRateProvider

logger = logging.getLogger(__name__)

#: The bearer token authenticates the REQUEST, not a person -- there is
#: exactly one operator credential per deployment (``admin_auth``'s own
#: module docstring). Recorded as the ``decided_by`` actor on every
#: approval/rejection this router makes, defined once so no call site ever
#: invents a per-request identity that does not exist.
ADMIN_ACTOR = "admin"  # the holder of ADMIN_API_TOKEN

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
    venue_net_base: Decimal
    ledger_net_base: Decimal
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


# --------------------------------------------------------------------------
# Unit 7 -- admin endpoints for booking proposals (design.md § 12, § 16;
# spec: venue-close-booking's "Admin Endpoints Require the Bearer Token"
# and "DRY_RUN Refuses Booking Entirely" requirements).
#
# ``ApproveBooking``/``RejectBooking`` are fully implemented and tested
# (Units 6a/6b) -- everything below only WIRES them behind this router's
# already-structural auth. No new use-case logic lives here.
# --------------------------------------------------------------------------


class ProposedFillView(BaseModel):
    """One element of a proposal's frozen ``fills`` snapshot. Every money
    field is a STRING -- see ``BookingProposalView``'s own docstring for
    why."""

    exchange_fill_id: str
    exchange_order_id: str | None
    side: str
    quantity: str
    price: str
    fee: str
    fee_currency: str
    filled_at: datetime

    @classmethod
    def of(cls, fill: ProposedFillSnapshot) -> "ProposedFillView":
        return cls(
            exchange_fill_id=fill.exchange_fill_id,
            exchange_order_id=fill.exchange_order_id,
            side=fill.side,
            quantity=str(fill.quantity),
            price=str(fill.price),
            fee=str(fill.fee),
            fee_currency=fill.fee_currency,
            filled_at=fill.filled_at,
        )


class BookingProposalView(BaseModel):
    """The frozen snapshot in full, plus the mutable decision columns, as an
    operator reads it back (spec: "the frozen snapshot in full").

    Every money field is typed ``str`` on purpose, never ``Decimal``:
    FastAPI's default ``Decimal`` encoder
    (``fastapi.encoders.decimal_encoder``) turns a fractional value into a
    ``float`` on the wire, which silently loses precision an append-only
    ledger depends on -- design.md § 3 states the identical rule for the
    frozen ``fills`` JSONB column, and it applies equally to every other
    money field this view exposes.
    """

    id: UUID
    discrepancy_id: UUID
    exchange: str
    venue: str
    settlement_currency: str
    symbol: str
    kind: DiscrepancyKind
    allocation_id: UUID
    strategy_id: UUID
    side: str
    quantity: str
    observed_venue_net_base: str
    observed_ledger_net_base: str
    observed_allocation_ids: tuple[UUID, ...]
    fills: tuple[ProposedFillView, ...]
    client_order_id: str
    expires_at: datetime
    prepared_by_job_id: UUID
    created_at: datetime
    state: str
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    execution_attempt_id: UUID | None

    @classmethod
    def of(cls, record: BookingProposalRecord) -> "BookingProposalView":
        return cls(
            id=record.id,
            discrepancy_id=record.discrepancy_id,
            exchange=record.exchange,
            venue=record.venue,
            settlement_currency=record.settlement_currency,
            symbol=record.symbol,
            kind=record.kind,
            allocation_id=record.allocation_id,
            strategy_id=record.strategy_id,
            side=record.side,
            quantity=str(record.quantity),
            observed_venue_net_base=str(record.observed_venue_net_base),
            observed_ledger_net_base=str(record.observed_ledger_net_base),
            observed_allocation_ids=record.observed_allocation_ids,
            fills=tuple(ProposedFillView.of(fill) for fill in record.fills),
            client_order_id=record.client_order_id,
            expires_at=record.expires_at,
            prepared_by_job_id=record.prepared_by_job_id,
            created_at=record.created_at,
            state=record.state,
            decided_at=record.decided_at,
            decided_by=record.decided_by,
            decision_reason=record.decision_reason,
            execution_attempt_id=record.execution_attempt_id,
        )


class ApproveResponseBody(BaseModel):
    outcome: str
    execution_attempt_id: UUID | None = None
    ledger_entries_written: int = 0


class RejectResponseBody(BaseModel):
    outcome: str
    reason: str | None = None


class RefusalBody(BaseModel):
    """The flat shape every non-2xx approve/reject outcome returns --
    ``{outcome, detail}``, never FastAPI's own ``{"detail": ...}``
    ``HTTPException`` wrapper, so a caller reading a refused decision sees
    the SAME two keys regardless of which outcome refused it."""

    outcome: str
    detail: str


class RejectRequest(BaseModel):
    """``reason`` is REQUIRED at the schema level (an omitted body 422s
    automatically), but intentionally UNCONSTRAINED beyond that -- a blank
    or whitespace-only string must reach ``RejectBooking`` itself, which is
    the one place that decides ``REASON_REQUIRED`` (mirroring migration
    ``0023``'s own CHECK), rather than a schema-level rejection that would
    never exercise that business rule."""

    reason: str


#: Only one state is servable today -- ``BookingProposalRepositoryPort`` has
#: exactly one read method, ``list_pending`` (design.md § 12 names only the
#: pending list). Any other value 422s at the schema level, same as an
#: unsupported ``ResolutionFilter`` would.
_PendingOnly = Literal["pending"]


def _approve_use_case(session: SessionDep, settings: Settings) -> ApproveBooking:
    return ApproveBooking(
        proposals=SqlAlchemyBookingProposalRepository(session),
        discrepancies=SqlAlchemyDiscrepancyRepository(session),
        in_flight_close=InFlightCloseAdapter(SqlAlchemyExecutionAttemptRepository(session)),
        writer=SqlAlchemyBookingWriter(session),
        usd_rate_provider=FixedUsdRateProvider({Currency.USDT: Decimal("1")}),
        clock=SystemClock(),
        commit=session,
        # "Checked at the endpoint": ``settings.dry_run`` is read HERE, at
        # request time, and forwarded -- "and the use case refuses too":
        # the actual business-rule check, its WARNING log and its outcome
        # all live inside ``ApproveBooking`` itself (design.md § 16). This
        # endpoint never re-checks or re-logs the same refusal, which would
        # produce the duplicate WARNING this unit's own review explicitly
        # forbids.
        dry_run=settings.dry_run,
    )


def _approve_refusal_detail(result: ApproveResult) -> str:
    if result.reason is not None:
        return result.reason
    if result.outcome is ApproveOutcome.ALREADY_DECIDED:
        return f"proposal {result.proposal_id} has already been decided"
    if result.outcome is ApproveOutcome.EXPIRED:
        return f"proposal {result.proposal_id} expired before it could be approved"
    return f"proposal {result.proposal_id} could not be approved ({result.outcome.value})"


@router.get("/bookings", response_model=list[BookingProposalView])
async def list_bookings(
    session: SessionDep,
    state: Annotated[_PendingOnly, Query()] = "pending",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    symbol: str | None = None,
) -> list[BookingProposalView]:
    del state  # the only servable value -- see ``_PendingOnly``'s own docstring
    records = await SqlAlchemyBookingProposalRepository(session).list_pending(limit=limit)
    if symbol is not None:
        # Same spelling-normalisation rule design.md § 13 states for every
        # other symbol-filtered endpoint: the proposal stores the MARKET
        # KEY, an operator may type a venue or marker spelling.
        wanted = market_key(symbol)
        records = [record for record in records if market_key(record.symbol) == wanted]
    return [BookingProposalView.of(record) for record in records]


@router.post("/bookings/{proposal_id}/approve")
async def approve_booking(
    proposal_id: UUID,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    use_case = _approve_use_case(session, settings)
    try:
        result = await use_case.approve(proposal_id, decided_by=ADMIN_ACTOR)
    except BookingProposalNotFound as exc:
        # Only the port's own not-found maps to 404. A NoResultFound from any
        # deeper read stays a 500, so it can never pose as a missing proposal.
        raise HTTPException(status_code=404, detail="no such booking proposal") from exc

    if result.outcome is ApproveOutcome.APPROVED:
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(
                ApproveResponseBody(
                    outcome=result.outcome.value,
                    execution_attempt_id=result.execution_attempt_id,
                    ledger_entries_written=result.ledger_rows,
                )
            ),
        )
    if result.outcome is ApproveOutcome.DRY_RUN_REFUSED:
        # 503, never 403 (design.md § 12): the endpoint exists and the
        # caller is authorised -- the DEPLOYMENT is configured not to do
        # this.
        return JSONResponse(
            status_code=503,
            content=jsonable_encoder(
                RefusalBody(
                    outcome=result.outcome.value,
                    detail="this deployment is running under DRY_RUN; booking approval is disabled",
                )
            ),
        )
    # ALREADY_DECIDED, SUPERSEDED, EXPIRED -- every outcome that either
    # wrote a state change or found one already written. Never 200: no
    # client can read a refused approval as success.
    return JSONResponse(
        status_code=409,
        content=jsonable_encoder(
            RefusalBody(outcome=result.outcome.value, detail=_approve_refusal_detail(result))
        ),
    )


@router.post("/bookings/{proposal_id}/reject")
async def reject_booking(
    proposal_id: UUID,
    body: RejectRequest,
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    use_case = RejectBooking(
        proposals=SqlAlchemyBookingProposalRepository(session),
        clock=SystemClock(),
        commit=session,
        # Same reasoning as ``_approve_use_case``: read here, enforced and
        # logged inside ``RejectBooking`` itself.
        dry_run=settings.dry_run,
    )
    try:
        result = await use_case.reject(proposal_id, decided_by=ADMIN_ACTOR, reason=body.reason)
    except BookingProposalNotFound as exc:
        raise HTTPException(status_code=404, detail="no such booking proposal") from exc

    if result.outcome is RejectOutcome.REJECTED:
        return JSONResponse(
            status_code=200,
            content=jsonable_encoder(
                RejectResponseBody(outcome=result.outcome.value, reason=result.reason)
            ),
        )
    if result.outcome is RejectOutcome.DRY_RUN_REFUSED:
        return JSONResponse(
            status_code=503,
            content=jsonable_encoder(
                RefusalBody(
                    outcome=result.outcome.value,
                    detail=(
                        "this deployment is running under DRY_RUN; "
                        "booking rejection is disabled"
                    ),
                )
            ),
        )
    if result.outcome is RejectOutcome.REASON_REQUIRED:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                RefusalBody(
                    outcome=result.outcome.value,
                    detail="a non-empty reason is required",
                )
            ),
        )
    # ALREADY_DECIDED
    return JSONResponse(
        status_code=409,
        content=jsonable_encoder(
            RefusalBody(
                outcome=result.outcome.value,
                detail=f"proposal {result.proposal_id} has already been decided",
            )
        ),
    )

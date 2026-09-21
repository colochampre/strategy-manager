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

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.reconciliation.application.market_key import market_key
from strategy_manager.reconciliation.application.ports import DiscrepancyRecord
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
)
from strategy_manager.reconciliation.infrastructure.repository import (
    SqlAlchemyDiscrepancyRepository,
)
from strategy_manager.shared.db import get_session
from strategy_manager.shared.infrastructure.admin_auth import require_admin_token

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

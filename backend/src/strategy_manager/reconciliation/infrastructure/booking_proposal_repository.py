"""SQLAlchemy implementation of ``BookingProposalRepositoryPort`` against the
``booking_proposals`` table (migration ``0023``).

Follows ``SqlAlchemyDiscrepancyRepository``'s own convention: the migration
is the schema's source of truth for every table-level constraint; this
repository's own discipline is the frozen-vs-mutable split migration
``0023``'s docstring documents -- ``insert`` writes every frozen column
exactly once, and ``mark_state`` is the ONLY method that ever changes
``state``/``decided_at``/``decided_by``/``decision_reason``/
``execution_attempt_id``, always through ``... WHERE id=:id AND
state='PENDING'`` (design.md § 3, "Concurrency without a lock table") --
never a bare ``UPDATE ... WHERE id=:id``.

``insert``'s one distinguishable, non-raising outcome is
``ux_booking_proposals_pending_per_discrepancy`` (a second PENDING proposal
for the same discrepancy), identified by the violated constraint's NAME via
``_constraint_name`` -- asyncpg wraps its own ``PostgresError`` (which
carries ``constraint_name`` directly) as ``__cause__`` of SQLAlchemy's DBAPI
wrapper exception, exactly the pattern
``tests/migrations/test_0023_booking_proposals.py`` already documents.
``insert`` runs inside its own SAVEPOINT so a caller sweeping several
discrepancies within one session/transaction can keep going past this one
collision, instead of aborting the whole transaction (design decision 6's
identical reasoning for ``SqlAlchemyBookingWriter``'s two named
``IntegrityError`` translations).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.reconciliation.application.ports import (
    BookingProposalNotFound,
    BookingProposalRecord,
    NewBookingProposal,
    ProposedFillSnapshot,
)
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind, Observation
from strategy_manager.reconciliation.infrastructure.models import BookingProposalRow

PENDING_PER_DISCREPANCY_CONSTRAINT = "ux_booking_proposals_pending_per_discrepancy"

_PENDING = "PENDING"
_REJECTED = "REJECTED"

_Row = BookingProposalRow


def _constraint_name(error: IntegrityError) -> str | None:
    """See module docstring. Identical helper to the one
    ``tests/migrations/test_0023_booking_proposals.py`` uses: reading
    ``error.orig.__cause__.constraint_name`` (NOT ``.orig.diag`` --
    psycopg's shape, not asyncpg's) is the only way this project's driver
    lets a caller identify a violated constraint BY NAME rather than by
    message text."""

    cause = error.orig.__cause__  # type: ignore[union-attr]
    return getattr(cause, "constraint_name", None)


def _require_aware(moment: datetime, what: str) -> None:
    """A naive datetime reaching a TIMESTAMPTZ column is read in the
    session's timezone: a wrong but plausible timestamp, with no error
    anywhere. Every clock in this system is timezone-aware, so a naive value
    can only be a bug, and it is refused before anything is written."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got naive {moment.isoformat()}")


def _fill_to_json(fill: ProposedFillSnapshot) -> dict[str, Any]:
    _require_aware(fill.filled_at, f"fill {fill.exchange_fill_id} filled_at")
    return {
        "exchange_fill_id": fill.exchange_fill_id,
        "exchange_order_id": fill.exchange_order_id,
        "side": fill.side,
        "quantity": str(fill.quantity),
        "price": str(fill.price),
        "fee": str(fill.fee),
        "fee_currency": fill.fee_currency,
        "filled_at": fill.filled_at.isoformat(),
    }


def _fill_from_json(payload: dict[str, Any]) -> ProposedFillSnapshot:
    return ProposedFillSnapshot(
        exchange_fill_id=payload["exchange_fill_id"],
        exchange_order_id=payload["exchange_order_id"],
        side=payload["side"],
        quantity=Decimal(payload["quantity"]),
        price=Decimal(payload["price"]),
        fee=Decimal(payload["fee"]),
        fee_currency=payload["fee_currency"],
        filled_at=datetime.fromisoformat(payload["filled_at"]),
    )


def _to_domain(row: BookingProposalRow) -> BookingProposalRecord:
    return BookingProposalRecord(
        id=row.id,
        discrepancy_id=row.discrepancy_id,
        exchange=row.exchange,
        venue=row.venue,
        settlement_currency=row.settlement_currency,
        symbol=row.symbol,
        kind=DiscrepancyKind(row.kind),
        allocation_id=row.allocation_id,
        strategy_id=row.strategy_id,
        side=row.side,
        quantity=row.quantity,
        observed_venue_net_base=row.observed_venue_net_base,
        observed_ledger_net_base=row.observed_ledger_net_base,
        observed_allocation_ids=tuple(row.observed_allocation_ids),
        fills=tuple(_fill_from_json(item) for item in row.fills),
        client_order_id=row.client_order_id,
        expires_at=row.expires_at,
        prepared_by_job_id=row.prepared_by_job_id,
        created_at=row.created_at,
        state=row.state,
        decided_at=row.decided_at,
        decided_by=row.decided_by,
        decision_reason=row.decision_reason,
        execution_attempt_id=row.execution_attempt_id,
    )


class SqlAlchemyBookingProposalRepository:
    """Implements ``reconciliation.application.ports.BookingProposalRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, proposal: NewBookingProposal) -> BookingProposalRecord | None:
        _require_aware(proposal.expires_at, "expires_at")
        row = _Row(
            discrepancy_id=proposal.discrepancy_id,
            exchange=proposal.exchange,
            venue=proposal.venue,
            settlement_currency=proposal.settlement_currency,
            symbol=proposal.symbol,
            kind=proposal.kind.value,
            allocation_id=proposal.allocation_id,
            strategy_id=proposal.strategy_id,
            side=proposal.side,
            quantity=proposal.quantity,
            observed_venue_net_base=proposal.observed_venue_net_base,
            observed_ledger_net_base=proposal.observed_ledger_net_base,
            observed_allocation_ids=list(proposal.observed_allocation_ids),
            fills=[_fill_to_json(fill) for fill in proposal.fills],
            client_order_id=proposal.client_order_id,
            expires_at=proposal.expires_at,
            prepared_by_job_id=proposal.prepared_by_job_id,
        )
        try:
            # A SAVEPOINT, not the outer transaction -- see module
            # docstring: a caller sweeping several discrepancies in one
            # session must be able to continue past this one collision.
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError as error:
            if _constraint_name(error) == PENDING_PER_DISCREPANCY_CONSTRAINT:
                return None
            raise
        return _to_domain(row)

    async def get_for_update(self, proposal_id: UUID) -> BookingProposalRecord:
        # ``FOR UPDATE`` is load-bearing for the CALLER's transaction, not
        # for this table's own CAS: ``mark_state``'s ``WHERE ... AND
        # state='PENDING'`` already re-evaluates against the committed row
        # once a blocking writer releases it, which is why this file's own
        # concurrency test still passes even with this clause removed
        # (proven during apply, then reverted -- see the commit message).
        # The lock instead protects everything the CALLER does BETWEEN
        # reading this row and calling ``mark_state`` -- Unit 6a's
        # ``ApproveBooking`` reads the freshness triple, resolves
        # ``usd_rate`` and writes ``execution_attempts``/``ledger_entries``
        # in that gap, and two unlocked approvals could both do that
        # expensive, side-effecting work before either commits, even
        # though only one of their later ``mark_state`` calls would win.
        row = (
            await self._session.execute(
                select(_Row).where(_Row.id == proposal_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise BookingProposalNotFound(f"no booking proposal {proposal_id}")
        return _to_domain(row)

    async def mark_state(
        self,
        proposal_id: UUID,
        state: str,
        at: datetime,
        *,
        decided_by: str | None = None,
        decision_reason: str | None = None,
        execution_attempt_id: UUID | None = None,
    ) -> bool:
        _require_aware(at, "decided_at")
        # The repository's ONLY update: the CAS guard is load-bearing, not
        # style -- see module docstring and design.md § 3.
        stmt = (
            update(_Row)
            .where(_Row.id == proposal_id, _Row.state == _PENDING)
            .values(
                state=state,
                decided_at=at,
                decided_by=decided_by,
                decision_reason=decision_reason,
                execution_attempt_id=execution_attempt_id,
            )
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        await self._session.flush()
        return result.rowcount == 1

    async def list_pending(self, limit: int = 100) -> list[BookingProposalRecord]:
        stmt = (
            select(_Row).where(_Row.state == _PENDING).order_by(_Row.expires_at.asc()).limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def has_matching_rejection(
        self, discrepancy_id: UUID, observation: Observation
    ) -> bool:
        stmt = (
            select(_Row.id)
            .where(
                _Row.discrepancy_id == discrepancy_id,
                _Row.state == _REJECTED,
                _Row.kind == observation.kind.value,
                _Row.observed_venue_net_base == observation.venue_net_base,
                _Row.observed_ledger_net_base == observation.ledger_net_base,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.first() is not None

    async def expire_pending(self, now: datetime) -> int:
        _require_aware(now, "now")
        stmt = (
            update(_Row)
            .where(_Row.state == _PENDING, _Row.expires_at <= now)
            .values(state="EXPIRED", decided_at=now)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        await self._session.flush()
        return result.rowcount

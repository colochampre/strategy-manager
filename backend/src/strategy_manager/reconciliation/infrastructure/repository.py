"""SQLAlchemy implementation of ``DiscrepancyRepositoryPort`` against the
``reconciliation_discrepancies`` table (migration ``0020``).

``upsert_open`` is a single ``INSERT ... ON CONFLICT`` rather than a
SELECT-then-branch: the partial unique index
``ux_reconciliation_open_per_symbol`` (on ``(exchange, venue,
settlement_currency, symbol) WHERE resolved_at IS NULL``) is exactly the
conflict target Postgres infers from ``index_elements``/``index_where``
below, so "insert on the first observation, update in place afterward" is
one atomic statement rather than a race between a read and a write.

``ON CONFLICT ON CONSTRAINT`` cannot be used here: that clause only matches a
constraint created by ``ADD CONSTRAINT`` (a UNIQUE/PRIMARY KEY/EXCLUDE
constraint), and this is a partial *index* created by ``CREATE UNIQUE INDEX
... WHERE`` — a real distinction in Postgres, not a naming choice. Index
inference (``index_elements`` + ``index_where``) is the form that matches it.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from strategy_manager.reconciliation.application.ports import (
    DiscrepancyRecord,
    PoolKey,
)
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.infrastructure.models import (
    ReconciliationDiscrepancyRow,
)

_Row = ReconciliationDiscrepancyRow


def _to_domain(row: ReconciliationDiscrepancyRow) -> DiscrepancyRecord:
    return DiscrepancyRecord(
        id=row.id,
        exchange=row.exchange,
        venue=row.venue,
        settlement_currency=row.settlement_currency,
        symbol=row.symbol,
        kind=DiscrepancyKind(row.kind),
        venue_net_base=row.venue_net_base,
        ledger_net_base=row.ledger_net_base,
        open_allocation_ids=tuple(row.open_allocation_ids),
        consecutive_scans=row.consecutive_scans,
        status=DiscrepancyStatus(row.status),
        first_observed_at=row.first_observed_at,
        last_observed_at=row.last_observed_at,
        confirmed_at=row.confirmed_at,
        resolved_at=row.resolved_at,
        first_scan_id=row.first_scan_id,
        last_scan_id=row.last_scan_id,
        resolved_by_scan_id=row.resolved_by_scan_id,
    )


class SqlAlchemyDiscrepancyRepository:
    """Implements ``reconciliation.application.ports.DiscrepancyRepositoryPort``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_discrepancies(
        self,
        pool: PoolKey | None = None,
        status: DiscrepancyStatus | None = None,
        open_only: bool = False,
    ) -> list[DiscrepancyRecord]:
        stmt = select(_Row)
        if pool is not None:
            exchange, venue, settlement_currency = pool
            stmt = stmt.where(
                _Row.exchange == exchange,
                _Row.venue == venue,
                _Row.settlement_currency == settlement_currency,
            )
        if status is not None:
            stmt = stmt.where(_Row.status == status.value)
        if open_only:
            stmt = stmt.where(_Row.resolved_at.is_(None))

        result = await self._session.execute(stmt)
        return [_to_domain(row) for row in result.scalars().all()]

    async def upsert_open(
        self,
        pool: PoolKey,
        symbol: str,
        observation: Observation,
        open_allocation_ids: Sequence[UUID],
        consecutive_scans: int,
        status: DiscrepancyStatus,
        scan_id: UUID,
        at: datetime,
    ) -> None:
        exchange, venue, settlement_currency = pool
        # Computed once, in Python: this is what ``excluded.confirmed_at``
        # resolves to below, on BOTH the insert and the conflict branch.
        confirmed_at = at if status is DiscrepancyStatus.CONFIRMED else None

        insert_stmt = pg_insert(_Row).values(
            exchange=exchange,
            venue=venue,
            settlement_currency=settlement_currency,
            symbol=symbol,
            kind=observation.kind.value,
            venue_net_base=observation.venue_net_base,
            ledger_net_base=observation.ledger_net_base,
            open_allocation_ids=list(open_allocation_ids),
            consecutive_scans=consecutive_scans,
            status=status.value,
            first_observed_at=at,
            last_observed_at=at,
            confirmed_at=confirmed_at,
            first_scan_id=scan_id,
            last_scan_id=scan_id,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[_Row.exchange, _Row.venue, _Row.settlement_currency, _Row.symbol],
            index_where=_Row.resolved_at.is_(None),
            set_={
                "kind": insert_stmt.excluded.kind,
                "venue_net_base": insert_stmt.excluded.venue_net_base,
                "ledger_net_base": insert_stmt.excluded.ledger_net_base,
                "open_allocation_ids": insert_stmt.excluded.open_allocation_ids,
                "consecutive_scans": insert_stmt.excluded.consecutive_scans,
                "status": insert_stmt.excluded.status,
                "last_observed_at": insert_stmt.excluded.last_observed_at,
                "last_scan_id": insert_stmt.excluded.last_scan_id,
                # "First confirmed at": set the first time status becomes
                # CONFIRMED and never touched again, INCLUDING when a moved
                # observation demotes the row back to OBSERVED. The CHECK is
                # a one-way implication precisely so this coalesce is legal
                # -- erasing the timestamp on every wobble would destroy the
                # record that the disagreement was once confirmed. Read
                # ``status`` to ask whether a row is confirmed NOW.
                "confirmed_at": func.coalesce(_Row.confirmed_at, insert_stmt.excluded.confirmed_at),
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def resolve_absent(
        self,
        pool: PoolKey,
        symbols: Sequence[str],
        scan_id: UUID,
        at: datetime,
    ) -> int:
        if not symbols:
            return 0
        exchange, venue, settlement_currency = pool
        stmt = (
            update(_Row)
            .where(
                _Row.exchange == exchange,
                _Row.venue == venue,
                _Row.settlement_currency == settlement_currency,
                _Row.symbol.in_(symbols),
                _Row.resolved_at.is_(None),
            )
            .values(resolved_at=at, resolved_by_scan_id=scan_id)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        await self._session.flush()
        return result.rowcount

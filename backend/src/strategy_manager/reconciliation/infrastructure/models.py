"""SQLAlchemy ORM model owned by ``reconciliation``. Mirrors migration
``0020``'s ``reconciliation_discrepancies`` table.

Following ``ExecutionAttemptRow``'s convention: the migration is the schema's
source of truth for anything expressed as a table-level constraint (the
composite FK, every CHECK, the two partial indexes). This model maps column
shape only, so there is exactly one place those rules can drift from what the
database actually enforces.

``delta_base`` is mapped with the same ``Computed(...)`` expression the
migration installs, not as an ordinary column. That is what tells SQLAlchemy
to exclude it from every INSERT/UPDATE it generates — the column is
``GENERATED ALWAYS ... STORED`` and Postgres refuses a write that even
mentions it.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Computed, DateTime, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY as PGARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from strategy_manager.shared.db import Base


class ReconciliationDiscrepancyRow(Base):
    """Mirrors the ``reconciliation_discrepancies`` table created by
    migration ``0020``."""

    __tablename__ = "reconciliation_discrepancies"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    venue: Mapped[str] = mapped_column(Text, nullable=False)
    settlement_currency: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    # ``ck_reconciliation_discrepancies_kind`` (migration ``0020``): the four
    # verdicts of the classification ladder.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    venue_net_base: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    ledger_net_base: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    # GENERATED ALWAYS AS (venue_net_base - ledger_net_base) STORED. Read-only:
    # never set on an instance, never included in an INSERT or UPDATE.
    delta_base: Mapped[Decimal] = mapped_column(
        Numeric(38, 18),
        Computed("venue_net_base - ledger_net_base", persisted=True),
        nullable=False,
    )
    open_allocation_ids: Mapped[list[UUID]] = mapped_column(
        PGARRAY(PGUUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    )
    # ``ck_reconciliation_discrepancies_consecutive_scans_positive``.
    consecutive_scans: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    # ``ck_reconciliation_discrepancies_status``.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="OBSERVED")
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # "First confirmed at", not "is confirmed".
    # ``ck_reconciliation_discrepancies_confirmed_at`` requires this whenever
    # ``status`` is CONFIRMED, but permits it to outlive a demotion back to
    # OBSERVED, so a row that was confirmed and has since moved keeps the
    # timestamp. Ask ``status`` whether a row is confirmed NOW.
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ``jobs.id`` values, carrying no foreign key on purpose (module
    # docstring of migration ``0020``): jobs are pruned, discrepancies outlive
    # the scan that found them.
    first_scan_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    last_scan_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    resolved_by_scan_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

"""reconciliation_discrepancies: what reconciliation.scan found disagreeing
between a venue's own reported net position and the ledger's.

A discrepancy is evidence, not a cache entry: the composite FK to
``capital_pools`` carries no ``ON DELETE CASCADE``, on purpose, unlike
``pool_balance_snapshots``' FK (migration ``0009``/``0018``). A snapshot is a
disposable read of current state and disappearing with its pool is correct.
A discrepancy is a RECORD that something did not add up, and deleting the
pool it points at must not make that record vanish with it -- an operator has
to resolve it first. ``capital_pools_pkey`` is
``(exchange, venue, settlement_currency)`` (migration ``0018``), so the FK is
composite in the same three columns, in the same order every other table
referencing it already uses (``strategies``, ``reservations``,
``pool_balance_snapshots``).

``delta_base`` is a generated, stored column rather than something the
application computes and writes: ``venue_net_base - ledger_net_base`` can
never drift from the two numbers it is derived from, and a reader never has
to recompute it to filter or sort by the size of a discrepancy.

The partial unique index follows the exact pattern
``ux_exchange_credentials_one_active_per_exchange`` (migration ``0010``)
established for "at most one CURRENT row per key, history stays": at most one
OPEN (``resolved_at IS NULL``) discrepancy may exist per pool+symbol, but a
resolved one is never deleted, only superseded once the venue and the ledger
disagree again.

The ``status``/``confirmed_at`` CHECK is a ONE-WAY implication, not an
equivalence: a row cannot claim ``CONFIRMED`` without a timestamp saying
when that happened, but it MAY carry that timestamp while back at
``OBSERVED``.

That asymmetry is deliberate, and an equivalence here is an outright bug.
``consecutive_scans`` resets to 1 whenever an observation moves in kind or
in either quantity, which demotes a previously CONFIRMED row to
``OBSERVED`` -- the in-flight case the scan refuses to handle by skipping.
Under an equivalence the repository would have to erase ``confirmed_at`` on
that demotion, destroying the record that this disagreement once held still
long enough to be confirmed, every time it wobbled. So ``confirmed_at``
means "first confirmed at": written once, never cleared.

**Consequence for anyone reading this table**: a row is currently confirmed
when ``status = 'CONFIRMED'``, NOT when ``confirmed_at IS NOT NULL``.
Filtering on the timestamp also returns every row that was confirmed once
and has since moved.

``open_allocation_ids`` is stored rather than re-derived so that slice 2,
which acts on a CONFIRMED row, sees the allocations that were open at the
moment the disagreement was observed -- by then the ledger may have moved on.

The three ``*_scan_id`` columns hold ``jobs.id`` values but carry NO foreign
key, deliberately: jobs are transient and get pruned, and a discrepancy must
outlive the scan that found it. A dangling scan id is a lost breadcrumb; a
cascade from job cleanup would be a lost piece of evidence.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "reconciliation_discrepancies"
_POOL_COLUMNS = ["exchange", "venue", "settlement_currency"]
_KNOWN_EXCHANGES = "exchange IN ('pionex','bybit','binance')"

# The four verdicts of the classification ladder. Order matters to the domain
# rule, not to this CHECK: the ladder picks ATTRIBUTABLE_FULL_CLOSE over
# ATTRIBUTABLE_SINGLE_ALLOCATION when both fit, so that a single observation
# never oscillates between two labels and resets consecutive_scans forever.
_KNOWN_KINDS = (
    "kind IN ("
    "'ATTRIBUTABLE_SINGLE_ALLOCATION',"
    "'ATTRIBUTABLE_FULL_CLOSE',"
    "'AMBIGUOUS_PARTIAL_REDUCE',"
    "'NO_MATCHING_ALLOCATION'"
    ")"
)
_KNOWN_STATUSES = "status IN ('OBSERVED','CONFIRMED')"
# One-way implication, NOT an equivalence -- see the module docstring. A
# demoted row keeps the timestamp of the confirmation it once earned.
_CONFIRMED_HAS_TIMESTAMP = "status <> 'CONFIRMED' OR confirmed_at IS NOT NULL"

_OPEN_UNIQUE_INDEX = "ux_reconciliation_open_per_symbol"
_OPEN_LOOKUP_INDEX = "ix_reconciliation_open"
_LEDGER_POOL_SYMBOL_INDEX = "ix_ledger_pool_symbol"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("venue_net_base", sa.Numeric(38, 18), nullable=False),
        sa.Column("ledger_net_base", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "delta_base",
            sa.Numeric(38, 18),
            sa.Computed("venue_net_base - ledger_net_base", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "open_allocation_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column(
            "consecutive_scans", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="OBSERVED"),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_by_scan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            _POOL_COLUMNS,
            [f"capital_pools.{column}" for column in _POOL_COLUMNS],
            name="fk_reconciliation_discrepancies_capital_pool",
            # Deliberately no ON DELETE CASCADE -- see module docstring.
        ),
        sa.CheckConstraint(
            _KNOWN_EXCHANGES, name="ck_reconciliation_discrepancies_exchange"
        ),
        sa.CheckConstraint(_KNOWN_KINDS, name="ck_reconciliation_discrepancies_kind"),
        sa.CheckConstraint(
            _KNOWN_STATUSES, name="ck_reconciliation_discrepancies_status"
        ),
        sa.CheckConstraint(
            _CONFIRMED_HAS_TIMESTAMP,
            name="ck_reconciliation_discrepancies_confirmed_at",
        ),
        sa.CheckConstraint(
            "consecutive_scans >= 1",
            name="ck_reconciliation_discrepancies_consecutive_scans_positive",
        ),
    )
    op.create_index(
        _OPEN_UNIQUE_INDEX,
        _TABLE,
        [*_POOL_COLUMNS, "symbol"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        _OPEN_LOOKUP_INDEX,
        _TABLE,
        _POOL_COLUMNS,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index(
        _LEDGER_POOL_SYMBOL_INDEX,
        "ledger_entries",
        [*_POOL_COLUMNS, "symbol"],
    )


def downgrade() -> None:
    op.drop_index(_LEDGER_POOL_SYMBOL_INDEX, table_name="ledger_entries")
    op.drop_index(_OPEN_LOOKUP_INDEX, table_name=_TABLE)
    op.drop_index(_OPEN_UNIQUE_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)

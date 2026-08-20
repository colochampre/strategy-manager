"""pool_balance_snapshots: the local landing table for exchange balances.

``BalanceSourcePort`` forbids a remote implementation, because a synchronous
HTTP call would run inside ``pg_advisory_xact_lock`` and serialize every
allocation on that pool behind exchange latency. This table is what closes
that gap: a background job writes what the exchange reported, and the
allocation path reads it as a local primary-key lookup.

One row per pool, upserted rather than appended. The read happens while the
pool's advisory lock is held, so it must be the cheapest lookup available;
balance history is not lost by this choice because every fill is already
recorded in the append-only ledger.

``observed_at`` is when the exchange reported the figure, NOT when the row was
written. Readers reject a snapshot that is too old, so the distinction is the
whole safety mechanism rather than bookkeeping.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "pool_balance_snapshots"
_NON_NEGATIVE = "ck_pool_balance_snapshots_available_non_negative"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("available", sa.Numeric(38, 18), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("venue", "settlement_currency"),
        # capital_pools stays the single source of truth for which pools
        # exist: a snapshot for an unconfigured pool cannot be written, and
        # deleting a pool takes its snapshot with it.
        sa.ForeignKeyConstraint(
            ["venue", "settlement_currency"],
            ["capital_pools.venue", "capital_pools.settlement_currency"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("available >= 0", name=_NON_NEGATIVE),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)

"""Record a pool's total alongside what is still available.

A strategy's ``allocation_percent`` is a share of the pool's TOTAL (owner
decision 2026-09-15). Until now the snapshot held only what was still free,
and for a futures pool that figure shrinks as soon as a position opens,
because its margin is committed. Three strategies at 30% each therefore asked
for 30%, 21% and 14.7% of the starting pool when a sync ran between their
signals, and 30% each when it did not -- the same configuration opening
different sizes depending on job timing.

``total`` is the sizing base. ``available`` stays the ceiling on every grant.

Existing rows are backfilled with ``total = available``. That understates a
pool with open positions, but only until the next ``balance.sync`` rewrites
the row, and the allocation path already refuses a snapshot older than a few
sync intervals.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "pool_balance_snapshots"
_TOTAL_COVERS_AVAILABLE = "ck_pool_balance_snapshots_total_covers_available"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("total", sa.Numeric(38, 18), nullable=True))
    op.execute(f"UPDATE {_TABLE} SET total = available")
    op.alter_column(_TABLE, "total", nullable=False)
    # Availability is the total minus what is committed, so it can never
    # exceed it. A row that says otherwise was mapped from the wrong fields.
    op.create_check_constraint(_TOTAL_COVERS_AVAILABLE, _TABLE, "total >= available")


def downgrade() -> None:
    op.drop_constraint(_TOTAL_COVERS_AVAILABLE, _TABLE)
    op.drop_column(_TABLE, "total")

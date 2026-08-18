"""strategies.allocation_percent + range CHECK (design.md § "Order size
never comes from the alert"; tasks.md 7.5).

``DEFAULT 100`` preserves current behaviour for any existing row: prior to
this slice every strategy implicitly requested its whole pool balance on
every consuming signal (design.md's GAP FOUND note), so 100% is the
backward-compatible default rather than a new restriction.

Revision ID: 0007
Revises: 0005
Create Date: 2026-08-18

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_CHECK_NAME = "ck_strategies_allocation_percent_range"


def upgrade() -> None:
    op.add_column(
        "strategies",
        sa.Column(
            "allocation_percent",
            sa.Numeric(),
            nullable=False,
            server_default="100",
        ),
    )
    op.create_check_constraint(
        _CHECK_NAME,
        "strategies",
        "allocation_percent > 0 AND allocation_percent <= 100",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "strategies", type_="check")
    op.drop_column("strategies", "allocation_percent")

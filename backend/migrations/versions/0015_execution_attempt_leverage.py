"""Record the leverage a futures order was sized at.

A futures order's size means nothing on its own. The allocation engine grants
MARGIN out of the futures wallet, and the position that margin supports is
``granted * leverage / price`` -- so the same base size at 5x and at 20x is a
completely different fraction of the pool, opened against a completely
different amount of reserved capital.

Leverage is a per-symbol ACCOUNT setting that the owner can change from
Pionex's own UI at any time, which means it cannot be looked up later and
trusted to be the number that was in force. Reading it at settlement, or when
reporting PnL, would attribute a position to whatever multiple happens to be
configured when the question is asked. That is the same class of mistake as
backfilling a USD rate (CLAUDE.md rule 7): the fact is only true at the moment
it is captured.

So it is written once, on the attempt, at the moment the order is sized.

NULL means "not a futures order". Spot has no leverage, and defaulting it to 1
would make the column unable to distinguish a spot fill from a futures
position at 1x -- which are different things with different liquidation
behaviour.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_attempts",
        sa.Column("leverage", sa.Numeric(18, 8), nullable=True),
    )
    # A leverage of zero would divide a position to nothing; a negative one
    # would invert its direction. Neither is a number to keep.
    op.create_check_constraint(
        "ck_execution_attempts_leverage_positive",
        "execution_attempts",
        "leverage IS NULL OR leverage > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_execution_attempts_leverage_positive", "execution_attempts"
    )
    op.drop_column("execution_attempts", "leverage")

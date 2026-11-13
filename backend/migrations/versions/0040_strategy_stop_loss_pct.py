"""A strategy's stop level (subscriber-safety D5 and D6; tasks.md SS.3).

``strategies.stop_loss_pct`` is where a strategy's positions are stopped, as a
percentage of price from the entry: ``NUMERIC(4, 2)``, ``NOT NULL``, from 1 to 50
inclusive with at most two decimals (the type holds the two places, the CHECK the
range). Every strategy that exists when this runs receives 10 (D6), which caps a
seat's leverage at 9x. The column keeps a default of 10, the level the registration
form offers, and ``RegisterStrategy`` still requires a level of the caller.

The level also caps the leverage a seat may choose, in the application
(``shared.domain.leverage.max_leverage``); nothing in the database reads it.

**Downgrade.** Drops the CHECK and the column. It loses every level an author chose,
so once authors have chosen, the plan is fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "strategies"
_COLUMN = "stop_loss_pct"
_CHECK = "ck_strategies_stop_loss_pct_range"


def upgrade() -> None:
    # The server default fills every existing row with 10 in the same statement.
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Numeric(4, 2), nullable=False, server_default=sa.text("10")),
    )
    op.create_check_constraint(_CHECK, _TABLE, f"{_COLUMN} BETWEEN 1 AND 50")


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)

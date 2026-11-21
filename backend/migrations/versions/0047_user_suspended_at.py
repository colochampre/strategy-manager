"""When the admin suspended an account (openspec/changes/public-site, LS9, PS.13 S2).

A suspended account opens nothing new, while its closes keep running, and every
strategy it authored stops opening for every subscriber. The suspension is the
date alone: no reason and no author are stored. Nothing is backfilled: nobody is
suspended yet.

**Downgrade.** Refuses while anyone is suspended: dropping the column would lift
every suspension without a word. With nobody suspended it drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_COLUMN = "suspended_at"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    suspended = (
        op.get_bind()
        .execute(sa.text(f"SELECT count(*) FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL"))
        .scalar_one()
    )
    if suspended:
        raise RuntimeError(
            f"Refusing to downgrade 0047: {suspended} user(s) are suspended. "
            "Dropping the column would lift their suspension without a word."
        )
    op.drop_column(_TABLE, _COLUMN)

"""A user's display name (multi-user decision 27; tasks.md F.1).

The public list names a strategy's author (decisions 17 and 23), and an e-mail
never reaches another user. So ``users.display_name`` holds the name a user
chooses. It is nullable: nobody has one yet, and a user with none is simply not
shown. Nothing is backfilled.

The CHECK is the last line behind ``normalize_display_name``, which also refuses
what a CHECK reads badly. The unique index is on ``lower()``, so one name cannot be
taken twice by changing its case.

**Downgrade.** Drops the index, the CHECK and the column. With other users signed
up it loses the names they chose, so from then on the plan is fix-forward.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_COLUMN = "display_name"
_CHECK = "ck_users_display_name_shape"
_INDEX = "ux_users_display_name_lower"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))
    op.create_check_constraint(
        _CHECK,
        _TABLE,
        f"{_COLUMN} = btrim({_COLUMN}) AND char_length({_COLUMN}) BETWEEN 3 AND 30 "
        f"AND position('@' in {_COLUMN}) = 0",
    )
    op.create_index(_INDEX, _TABLE, [sa.text(f"lower({_COLUMN})")], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)

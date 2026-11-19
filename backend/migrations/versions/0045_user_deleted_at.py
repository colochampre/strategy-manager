"""When a user deleted their account (openspec/changes/account-deletion, S3).

The user row is kept, because the ledger and every record other users depend on
point at it (rule 6), and stops naming anyone: ``DeleteAccount`` sets the e-mail
to ``deleted-<id>@invalid``, removes the display name and sets ``deleted_at``.
The CHECK holds those three together, so a row marked deleted can never keep a
real address or a name. Nothing is backfilled: nobody has deleted an account yet.

**Downgrade.** Drops the CHECK and the column. A deleted account then reads as
an ordinary user whose e-mail nobody can sign in with, so the admin list would
show it again; its personal data stays gone.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_COLUMN = "deleted_at"
_CHECK = "ck_users_deleted_names_nobody"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        _CHECK,
        _TABLE,
        f"{_COLUMN} IS NULL OR (display_name IS NULL "
        "AND email = 'deleted-' || id::text || '@invalid')",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)

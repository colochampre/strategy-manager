"""The failed invitation-code attempts of each user (multi-user decision 41; tasks.md
K.4).

An invitation code is eight characters of Crockford's base32, 40 bits. Guessing one
online is stopped by counting each user's failures: a wrong code, a malformed one or
a dead one each write a row here, and a user with ``MAX_FAILED_ATTEMPTS`` rows in the
last ``ATTEMPT_WINDOW`` has every further code refused unread. A row says who and
when, nothing of the code or of the strategy it was tried on; the log line carries
those.

The read the limit makes, one user's rows since an instant, is served by an index on
``(user_id, attempted_at)``. Rows older than the window are pruned as the user's next
failure is written, so the table holds about the last hour. A user's rows go with
the user.

**Downgrade.** Drops the table. Nothing of value is lost: the rows only ever count
the last hour, and a downgrade forgets at most one hour of failures.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "invite_code_attempts"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_invite_code_attempts_user", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_invite_code_attempts_user_attempted_at", _TABLE, ["user_id", "attempted_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_invite_code_attempts_user_attempted_at", table_name=_TABLE)
    op.drop_table(_TABLE)

"""The ``users`` table (multi-user design AD1; tasks.md A.3).

**What a user is.** The e-mail Cloudflare Access verified (owner decision 1).
The table stores that address and when the user was first and last seen, and
nothing that could authenticate anyone: there is no password, because the app
has no login of its own.

**One address, one row.** ``ux_users_email`` makes the address unique, and
``ck_users_email_normalized`` makes the database refuse any spelling other than
the trimmed, lower-cased one ``normalize_email`` produces. Access reports what
the identity provider sent, and a provider may keep the case the person typed;
without the CHECK, a writer that forgot to normalise would create a second user
for the same person.

**No owner row here.** The owner becomes a user the way everyone does, on their
first signed-in request. So this migration needs no setting, and a fresh
database migrates exactly like production. The backfill of existing data to the
owner belongs to the migration that adds the owner columns (PR B), which finds
the owner's row already there.

**Downgrade.** Drops the table. What is lost is who signed in and when; nothing
references the table yet, and nothing about money lives in it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("email", name="ux_users_email"),
        sa.CheckConstraint(
            "email = lower(email) AND email !~ '[[:space:]]'", name="ck_users_email_normalized"
        ),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)

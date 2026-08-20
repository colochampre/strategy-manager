"""exchange_credentials: envelope-encrypted API keys at rest (CLAUDE.md rule 8).

No column here holds a readable secret. Each row carries a data key wrapped
by the master key, and the key/secret ciphertexts that data key protects. The
only plaintext is ``api_key_last4``, which is the most any client may ever
learn about a stored credential.

The partial unique index allows a credential to be superseded without
deleting it — the old row stays for audit with ``is_active = false``, while
at most one active credential per exchange can ever exist, so the worker's
lookup can never be ambiguous.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "exchange_credentials"
_ACTIVE_INDEX = "ux_exchange_credentials_one_active_per_exchange"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # The wrapped data key: encrypted under the master key, never stored bare.
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("api_key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("api_key_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("api_secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("api_secret_nonce", sa.LargeBinary(), nullable=False),
        # The only plaintext in the table, and deliberately so.
        sa.Column("api_key_last4", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("exchange", "label", name="ux_exchange_credentials_label"),
        sa.CheckConstraint(
            "char_length(api_key_last4) = 4", name="ck_exchange_credentials_last4_length"
        ),
    )
    op.create_index(
        _ACTIVE_INDEX,
        _TABLE,
        ["exchange"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index(_ACTIVE_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)

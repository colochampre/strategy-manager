"""signals table: idempotent TradingView alert ingress.

Persists the typed alert fields (``action``, ``contracts``, ``position_size``,
``price``, ``symbol``, ``signal_type``) as first-class columns, not just an
opaque payload blob — the open/close transition cannot be reconstructed
later without them (design.md § "position_size routes the signal").

``signals.strategy_id`` has no foreign key yet: the ``strategies`` table does
not exist until migration ``0003``, which adds referential integrity. This
revision only enforces ``NOT NULL``.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACCEPTED"),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("contracts", sa.Numeric(38, 18), nullable=False),
        sa.Column("position_size", sa.Numeric(38, 18), nullable=False),
        sa.Column("price", sa.Numeric(38, 18), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("signal_type", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(idempotency_key) BETWEEN 1 AND 200", name="ck_signals_idempotency_key_length"
        ),
        sa.CheckConstraint(
            "status IN ('ACCEPTED','PROCESSING','PROCESSED','REJECTED')",
            name="ck_signals_status",
        ),
        sa.CheckConstraint("price > 0", name="ck_signals_price_positive"),
    )
    op.create_index(
        "ux_signals_idempotency",
        "signals",
        ["strategy_id", "idempotency_key"],
        unique=True,
    )
    # Backs the "prior position_size for (strategy, symbol)" lookup that
    # PositionTransition.classify needs — the open/close transition cannot be
    # reconstructed later without it (design.md, tasks.md § Slice 2).
    op.create_index(
        "ix_signals_strategy_symbol_received_at",
        "signals",
        ["strategy_id", "symbol", sa.text("received_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_strategy_symbol_received_at", table_name="signals")
    op.drop_index("ux_signals_idempotency", table_name="signals")
    op.drop_table("signals")

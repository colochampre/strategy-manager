"""reservations table: the money invariant's persistence, written only inside
TXN-A under the pool's advisory lock (design.md § SQL Schema and Migration
Map, § Transaction Boundaries; spec: capital-allocation § Pool Availability).

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reservations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("amount > 0", name="ck_reservations_amount_positive"),
        sa.CheckConstraint(
            "status IN ('PENDING','SUBMITTED','FILLED','RELEASED','EXPIRED')",
            name="ck_reservations_status",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_reservations_strategy"
        ),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], name="fk_reservations_signal"),
        sa.ForeignKeyConstraint(
            ["venue", "settlement_currency"],
            ["capital_pools.venue", "capital_pools.settlement_currency"],
            name="fk_reservations_capital_pool",
        ),
    )
    # The availability query's index: only PENDING/SUBMITTED rows matter, and
    # only while still inside their TTL.
    op.create_index(
        "ix_reservations_active",
        "reservations",
        ["venue", "settlement_currency", "expires_at"],
        postgresql_where=sa.text("status IN ('PENDING','SUBMITTED')"),
    )


def downgrade() -> None:
    op.drop_index("ix_reservations_active", table_name="reservations")
    op.drop_table("reservations")

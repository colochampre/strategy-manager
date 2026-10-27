"""A signal reaches a subscription through a delivery (multi-user design AD5;
tasks.md C.2).

**What a row says.** ``signal_deliveries`` is one signal arriving at one
subscription. It carries the outcome the signal used to carry alone
(``status``, ``outcome_reason``, ``outcome_detail``, ``decided_at``), so that
two subscribers of one strategy each decide the same signal on their own.
``UNIQUE (signal_id, subscription_id)`` keeps a signal from reaching one
subscription twice.

**Backfill.** One delivery per existing signal, for the subscription 0031 gave
the author of the signal's strategy, copying the signal's outcome columns and
``received_at`` (as ``created_at``). A signal whose strategy has no author
subscription stops the migration before anything is written, naming the signal.
The signals' own outcome columns are copied, not dropped: nothing reads the
copy until C.7 moves the writers.

**Reservations and attempts.** ``reservations.delivery_id`` is filled through
``reservations.signal_id``. ``execution_attempts.delivery_id`` comes from the
attempt's own ``signal_id`` when it has one. An attempt written before 0025
has none, so it takes the delivery of the reservation it opened
(``reservation_id``) or closed (``closes_allocation_id``). For a close, that is
the opening signal's delivery: the closing signal was never recorded, and the
reservation names the same subscription, which is what a delivery is read for.
Production had 4 attempts without ``signal_id`` (pre-check, 2026-10-27).

**Expand now, contract later.** ``reservations.delivery_id`` stays NULLABLE and
the unique on ``reservations.signal_id`` stays. C.6 makes the first NOT NULL and
drops the second, in this same migration, together with the code that writes it.
While ``delivery_id`` can be NULL its UNIQUE refuses nothing, so dropping the
old guard now would leave no protection against a second reservation for one
signal.

**Downgrade.** Refuses when more than one user exists, as 0031's does, since
the old schema has one outcome per signal. It drops the new columns, their constraints and the
table; the signals still hold their outcome.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "signal_deliveries"
_UNIQUE = "ux_signal_deliveries_signal_subscription"
_STATUS = "ck_signal_deliveries_status"
_RESERVATION_FK = "fk_reservations_delivery"
_RESERVATION_UNIQUE = "ux_reservations_delivery"
_ATTEMPT_FK = "fk_execution_attempts_delivery"
_MAX_NAMED = 10

_AUTHOR_SUBSCRIPTION = """
    SELECT DISTINCT ON (sub.strategy_id) sub.strategy_id, sub.id, sub.user_id
      FROM subscriptions AS sub
      JOIN strategies AS st ON st.id = sub.strategy_id AND st.author_id = sub.user_id
     ORDER BY sub.strategy_id, sub.created_at, sub.id
"""


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _refuse_a_signal_without_an_author_subscription() -> None:
    """The backfill never invents a subscription and never skips a signal."""
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT s.id FROM signals AS s WHERE NOT EXISTS ("
                "SELECT 1 FROM subscriptions AS sub JOIN strategies AS st "
                "ON st.id = sub.strategy_id AND st.author_id = sub.user_id "
                "WHERE sub.strategy_id = s.strategy_id) ORDER BY s.received_at, s.id"
            )
        )
        .all()
    )
    if rows:
        shown = ", ".join(str(row[0]) for row in rows[:_MAX_NAMED])
        more = len(rows) - _MAX_NAMED
        named = shown if more <= 0 else f"{shown} and {more} more"
        raise RuntimeError(
            "0032 gives every signal a delivery for its strategy author's subscription; "
            f"{len(rows)} signals belong to a strategy whose author has none: {named}. "
            "Run 0031's backfill for that strategy, then migrate again."
        )


def upgrade() -> None:
    _refuse_a_signal_without_an_author_subscription()

    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACCEPTED"),
        sa.Column("outcome_reason", sa.Text(), nullable=True),
        sa.Column("outcome_detail", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], name="fk_signal_deliveries_signal"),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], name="fk_signal_deliveries_subscription"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_signal_deliveries_user"),
        sa.UniqueConstraint("signal_id", "subscription_id", name=_UNIQUE),
        sa.CheckConstraint(
            "status IN ('ACCEPTED','PROCESSING','PROCESSED','REJECTED')", name=_STATUS
        ),
    )
    op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])

    op.execute(
        f"""
        INSERT INTO {_TABLE} (id, signal_id, subscription_id, user_id, status, outcome_reason,
                              outcome_detail, decided_at, created_at)
        SELECT gen_random_uuid(), s.id, a.id, a.user_id, s.status, s.outcome_reason,
               s.outcome_detail, s.decided_at, s.received_at
          FROM signals AS s
          JOIN ({_AUTHOR_SUBSCRIPTION}) AS a(strategy_id, id, user_id)
            ON a.strategy_id = s.strategy_id
        """
    )

    op.add_column("reservations", sa.Column("delivery_id", postgresql.UUID(as_uuid=True)))
    op.execute(
        f"UPDATE reservations AS r SET delivery_id = d.id FROM {_TABLE} AS d "
        "WHERE d.signal_id = r.signal_id"
    )
    op.create_foreign_key(_RESERVATION_FK, "reservations", _TABLE, ["delivery_id"], ["id"])
    op.create_unique_constraint(_RESERVATION_UNIQUE, "reservations", ["delivery_id"])

    op.add_column("execution_attempts", sa.Column("delivery_id", postgresql.UUID(as_uuid=True)))
    # In order of precedence: the attempt's own signal, then the reservation
    # it opened, then the reservation it closed.
    op.execute(
        "UPDATE execution_attempts AS a SET delivery_id = d.id FROM signal_deliveries AS d "
        "WHERE a.signal_id IS NOT NULL AND d.signal_id = a.signal_id"
    )
    op.execute(
        "UPDATE execution_attempts AS a SET delivery_id = r.delivery_id FROM reservations AS r "
        "WHERE a.delivery_id IS NULL AND r.id = a.reservation_id"
    )
    op.execute(
        "UPDATE execution_attempts AS a SET delivery_id = r.delivery_id FROM reservations AS r "
        "WHERE a.delivery_id IS NULL AND r.id = a.closes_allocation_id"
    )
    op.create_foreign_key(_ATTEMPT_FK, "execution_attempts", _TABLE, ["delivery_id"], ["id"])


def downgrade() -> None:
    users = _count("SELECT count(*) FROM users")
    if users > 1:
        raise RuntimeError(
            "0032's downgrade folds every delivery back into its signal's single outcome, "
            f"which only holds for one user at most; found {users}. Fix forward instead."
        )

    op.drop_constraint(_ATTEMPT_FK, "execution_attempts", type_="foreignkey")
    op.drop_column("execution_attempts", "delivery_id")
    op.drop_constraint(_RESERVATION_UNIQUE, "reservations", type_="unique")
    op.drop_constraint(_RESERVATION_FK, "reservations", type_="foreignkey")
    op.drop_column("reservations", "delivery_id")
    op.drop_table(_TABLE)

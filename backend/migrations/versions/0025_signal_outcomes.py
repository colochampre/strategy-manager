"""``signals.outcome_reason``/``outcome_detail``/``decided_at`` and
``execution_attempts.signal_id`` (decision 25, owner-decisions.md 25-26;
design.md "Addendum: signal outcomes (decision 25)" § D; tasks.md PR 5b,
task 5b.2/5b.3).

Every processed signal now records what happened to it: a rejection stores
a stable reason code (design.md § B's reason-code table) and the
human-readable message already logged for that branch; ``decided_at`` marks
when the outcome became final. Both are additive, nullable columns -- no
existing row is touched, and every signal ingested before this migration
stays ``ACCEPTED`` forever (nothing is reconstructed, decision 25).

**The two CHECK constraints.**
``ck_signals_rejected_requires_outcome_reason``: a signal cannot be
``REJECTED`` without a reason code -- ahead of the DB, ``SignalOutcome``'s
own ``__post_init__`` (``signals/domain/outcome.py``) already refuses to
build that combination, so this CHECK is the second line of defense, not
the first.
``ck_signals_terminal_requires_decided_at``: a signal cannot be
``PROCESSED`` or ``REJECTED`` without a decision time -- the terminal-state
guard (``SqlAlchemySignalOutcomeAdapter``, design.md § A) always sets it
alongside a terminal status write, in the same flushed unit of work.

**``execution_attempts.signal_id``.** Nullable, FK to ``signals``. An
opening attempt already reaches its signal through
``reservation.signal_id`` (``reservation_id -> reservations.signal_id``,
migration ``0004``), so this column exists for the closing side, which has
no such route (design.md § C: ``CloseCommand`` carries
``allocation_id``, never ``signal_id``). It stays ``NULL`` for every
attempt written before PR 5c, the first unit to populate it; this
migration adds no seeding or backfill.

**The downgrade refusal.** Unlike a purely additive migration, dropping
these columns after outcomes exist would silently discard real recorded
history -- a signal's REJECTED reason, or a closing attempt's link back to
the signal it belongs to -- exactly the 0012/0021/0024 precedent this
change already follows twice. The downgrade refuses while ANY signal is
not ``ACCEPTED`` (i.e. an outcome was ever recorded) OR any
``execution_attempts`` row carries a non-null ``signal_id``, naming both
counts. There is no force flag: neither count is safe to discard, and
nothing here can regenerate either value once dropped.

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_SIGNALS = "signals"
_OUTCOME_REASON_COLUMN = "outcome_reason"
_OUTCOME_DETAIL_COLUMN = "outcome_detail"
_DECIDED_AT_COLUMN = "decided_at"
_REJECTED_REQUIRES_REASON_CHECK = "ck_signals_rejected_requires_outcome_reason"
_TERMINAL_REQUIRES_DECIDED_AT_CHECK = "ck_signals_terminal_requires_decided_at"

_EXECUTION_ATTEMPTS = "execution_attempts"
_SIGNAL_ID_COLUMN = "signal_id"
_SIGNAL_ID_FK = "fk_execution_attempts_signal"


def upgrade() -> None:
    op.add_column(
        _SIGNALS,
        sa.Column(_OUTCOME_REASON_COLUMN, sa.Text(), nullable=True),
    )
    op.add_column(
        _SIGNALS,
        sa.Column(_OUTCOME_DETAIL_COLUMN, sa.Text(), nullable=True),
    )
    op.add_column(
        _SIGNALS,
        sa.Column(_DECIDED_AT_COLUMN, sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        _REJECTED_REQUIRES_REASON_CHECK,
        _SIGNALS,
        f"status <> 'REJECTED' OR {_OUTCOME_REASON_COLUMN} IS NOT NULL",
    )
    op.create_check_constraint(
        _TERMINAL_REQUIRES_DECIDED_AT_CHECK,
        _SIGNALS,
        f"status NOT IN ('PROCESSED', 'REJECTED') OR {_DECIDED_AT_COLUMN} IS NOT NULL",
    )

    op.add_column(
        _EXECUTION_ATTEMPTS,
        sa.Column(_SIGNAL_ID_COLUMN, postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        _SIGNAL_ID_FK,
        _EXECUTION_ATTEMPTS,
        _SIGNALS,
        [_SIGNAL_ID_COLUMN],
        ["id"],
    )


def downgrade() -> None:
    bind: Connection = op.get_bind()

    non_accepted_count = bind.execute(
        sa.text(f"SELECT count(*) FROM {_SIGNALS} WHERE status <> 'ACCEPTED'")  # noqa: S608
    ).scalar_one()
    linked_attempts_count = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {_EXECUTION_ATTEMPTS} "  # noqa: S608
            f"WHERE {_SIGNAL_ID_COLUMN} IS NOT NULL"
        )
    ).scalar_one()

    if non_accepted_count > 0 or linked_attempts_count > 0:
        raise RuntimeError(
            f"Refusing to downgrade 0025_signal_outcomes: {non_accepted_count} {_SIGNALS} "
            f"row(s) are not ACCEPTED (an outcome was recorded) and {linked_attempts_count} "
            f"{_EXECUTION_ATTEMPTS} row(s) carry a non-null {_SIGNAL_ID_COLUMN}. Both record "
            "real decisions this migration did not create and cannot reconstruct "
            "(0012/0021/0024 precedent). This downgrade offers no force flag: neither "
            "count is safe to discard."
        )

    op.drop_constraint(_SIGNAL_ID_FK, _EXECUTION_ATTEMPTS, type_="foreignkey")
    op.drop_column(_EXECUTION_ATTEMPTS, _SIGNAL_ID_COLUMN)

    op.drop_constraint(_TERMINAL_REQUIRES_DECIDED_AT_CHECK, _SIGNALS, type_="check")
    op.drop_constraint(_REJECTED_REQUIRES_REASON_CHECK, _SIGNALS, type_="check")
    op.drop_column(_SIGNALS, _DECIDED_AT_COLUMN)
    op.drop_column(_SIGNALS, _OUTCOME_DETAIL_COLUMN)
    op.drop_column(_SIGNALS, _OUTCOME_REASON_COLUMN)

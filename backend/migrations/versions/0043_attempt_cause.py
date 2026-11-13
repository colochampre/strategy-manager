"""Why an execution attempt exists, and the ``FIRED`` stop status (subscriber-safety SS.7).

``execution_attempts.cause`` says what asked for the attempt:

* ``SIGNAL``: a strategy's signal (an opening, or the close it asked for);
* ``STOP``: a protective stop that fired at the venue, booked by the stop watcher;
* ``SAFETY_CLOSE``: the system closed a position by itself (SS.5's confirm job when a stop
  could not be shown to rest);
* ``MANUAL``: a trade done by hand at the venue, booked through reconciliation.

Rows written before this migration are backfilled by rule, in this order:

1. a ``signal_id`` gives ``SIGNAL``;
2. origin ``VENUE`` gives ``MANUAL``;
3. a ``SYSTEM`` close with no signal gives ``SAFETY_CLOSE`` (the only such close until now
   is SS.5's confirm job);
4. anything else gives ``SIGNAL``.

The upgrade prints the count per cause, which is what the rehearsal reads.

The column is NOT NULL and keeps a ``'SIGNAL'`` server default, as ``origin`` keeps its
``'SYSTEM'``: the default is what lets a raw INSERT of an older shape still land. The
Python ``ExecutionAttempt`` writers all name the cause explicitly.

``ck_protective_stops_status`` gains ``FIRED``: a stop that fired at the venue, whose
fills the watcher booked.

**Downgrade.** Refuses while a ``FIRED`` stop or a non-``SIGNAL`` cause exists, naming the
count, instead of losing what the system knows. There is no force flag: a ``STOP`` or
``MANUAL`` attempt has ledger rows behind it, and the append-only ledger forbids
discarding that history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ATTEMPTS = "execution_attempts"
_STOPS = "protective_stops"
_CAUSE_CHECK = "ck_execution_attempts_cause"
_STATUS_CHECK = "ck_protective_stops_status"
_CAUSES = ("SIGNAL", "STOP", "SAFETY_CLOSE", "MANUAL")
_OLD_STATUSES = "'PENDING', 'RESTING', 'FAILED', 'GONE', 'VOID', 'SIMULATED'"
_NEW_STATUSES = "'PENDING', 'RESTING', 'FIRED', 'FAILED', 'GONE', 'VOID', 'SIMULATED'"


def upgrade() -> None:
    op.add_column(_ATTEMPTS, sa.Column("cause", sa.Text(), nullable=True))
    # Rules in order: the first one that holds wins, so a VENUE booking that carries a
    # signal stays SIGNAL.
    op.execute(
        sa.text(
            f"UPDATE {_ATTEMPTS} SET cause = CASE "  # noqa: S608
            "WHEN signal_id IS NOT NULL THEN 'SIGNAL' "
            "WHEN origin = 'VENUE' THEN 'MANUAL' "
            "WHEN origin = 'SYSTEM' AND closes_allocation_id IS NOT NULL THEN 'SAFETY_CLOSE' "
            "ELSE 'SIGNAL' END"
        )
    )
    op.alter_column(_ATTEMPTS, "cause", nullable=False, server_default="SIGNAL")
    quoted = ", ".join(f"'{cause}'" for cause in _CAUSES)
    op.create_check_constraint(_CAUSE_CHECK, _ATTEMPTS, f"cause IN ({quoted})")

    op.drop_constraint(_STATUS_CHECK, _STOPS, type_="check")
    op.create_check_constraint(_STATUS_CHECK, _STOPS, f"status IN ({_NEW_STATUSES})")

    counts = dict(
        op.get_bind()
        .execute(sa.text(f"SELECT cause, count(*) FROM {_ATTEMPTS} GROUP BY cause"))  # noqa: S608
        .all()
    )
    print(  # noqa: T201 -- the rehearsal reads this line
        "execution_attempts.cause backfill: "
        + " ".join(f"{cause}={counts.get(cause, 0)}" for cause in _CAUSES)
    )


def downgrade() -> None:
    bind = op.get_bind()
    fired = bind.execute(
        sa.text(f"SELECT id FROM {_STOPS} WHERE status = 'FIRED'")  # noqa: S608
    ).all()
    if fired:
        ids = ", ".join(str(row[0]) for row in fired)
        raise RuntimeError(
            f"{len(fired)} protective_stops row(s) ({ids}) are FIRED, a status the pre-0043 "
            "shape cannot represent. Their fills are booked in the ledger under a STOP "
            "attempt; this downgrade will not lose that record."
        )
    others = bind.execute(
        sa.text(
            f"SELECT cause, count(*) FROM {_ATTEMPTS} "  # noqa: S608
            "WHERE cause <> 'SIGNAL' GROUP BY cause ORDER BY cause"
        )
    ).all()
    if others:
        summary = ", ".join(f"{row[0]}={row[1]}" for row in others)
        raise RuntimeError(
            f"execution_attempts rows carry a cause other than SIGNAL ({summary}), which the "
            "pre-0043 shape cannot represent. They have ledger rows behind them, and the "
            "append-only ledger forbids discarding that history, so this downgrade offers "
            "no force flag."
        )

    op.drop_constraint(_STATUS_CHECK, _STOPS, type_="check")
    op.create_check_constraint(_STATUS_CHECK, _STOPS, f"status IN ({_OLD_STATUSES})")
    op.drop_constraint(_CAUSE_CHECK, _ATTEMPTS, type_="check")
    op.drop_column(_ATTEMPTS, "cause")

"""When the admin suspended an account (openspec/changes/public-site, LS9, PS.13 S2).

A suspended account opens nothing new, while its closes keep running, and every
strategy it authored stops opening for every subscriber. The suspension is the
date alone: no reason and no author are stored. Nothing is backfilled: nobody is
suspended yet.

It also widens ``ck_safety_events_kind`` (0044) with the two kinds an opening refused for
a suspension is recorded as, ``OPENING_REFUSED_ACCOUNT_SUSPENDED`` and
``OPENING_REFUSED_AUTHOR_SUSPENDED`` (PS.13 S3, S4).

**Downgrade.** Refuses while anyone is suspended: dropping the column would lift
every suspension without a word. It also refuses while a safety event of either new
kind exists: the 0044 check would orphan it. With neither, it restores the 0044 check
and drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"
_COLUMN = "suspended_at"

_EVENTS_TABLE = "safety_events"
_KIND_CHECK = "ck_safety_events_kind"
_KINDS_0044 = (
    "STOP_FIRED",
    "STOP_FAILED_CLOSED",
    "STRATEGY_STOPPED_CLOSED",
    "MANUAL_CLOSE",
    "OPENING_REFUSED_LEVERAGE_CAP",
)
_NEW_KINDS = (
    "OPENING_REFUSED_ACCOUNT_SUSPENDED",
    "OPENING_REFUSED_AUTHOR_SUSPENDED",
)


def _replace_kind_check(kinds: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{kind}'" for kind in kinds)
    op.drop_constraint(_KIND_CHECK, _EVENTS_TABLE, type_="check")
    op.create_check_constraint(_KIND_CHECK, _EVENTS_TABLE, f"kind IN ({quoted})")


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True))
    _replace_kind_check(_KINDS_0044 + _NEW_KINDS)


def downgrade() -> None:
    bind = op.get_bind()
    suspended = bind.execute(
        sa.text(f"SELECT count(*) FROM {_TABLE} WHERE {_COLUMN} IS NOT NULL")
    ).scalar_one()
    if suspended:
        raise RuntimeError(
            f"Refusing to downgrade 0047: {suspended} user(s) are suspended. "
            "Dropping the column would lift their suspension without a word."
        )
    refusals = bind.execute(
        sa.text(f"SELECT count(*) FROM {_EVENTS_TABLE} WHERE kind IN :kinds").bindparams(
            sa.bindparam("kinds", _NEW_KINDS, expanding=True)
        )
    ).scalar_one()
    if refusals:
        raise RuntimeError(
            f"Refusing to downgrade 0047: {refusals} safety event(s) record an opening "
            "refused for a suspension. Restoring the 0044 check would orphan them."
        )
    _replace_kind_check(_KINDS_0044)
    op.drop_column(_TABLE, _COLUMN)

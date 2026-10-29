"""A strategy has its own webhook secret, a visibility and a per-author name
(multi-user design AD6, decisions 21 and 23; tasks.md D.1).

**The secret.** ``strategies.webhook_secret_hash`` is the SHA-256 hex of the
secret. Every existing strategy gets the hash of the current
``Settings.webhook_secret``, so the alerts TradingView already sends keep
working unchanged. The hash is computed here in Python: the secret never enters
SQL text, and no message names it. With strategies and no secret configured it
refuses before anything is written. The column stays nullable until the
registration writes it (D.3 adds the ``NOT NULL`` to this migration).

**Visibility.** ``strategies.visibility`` is ``PUBLIC`` or ``PRIVATE``; every
existing strategy is ``PRIVATE``, so nothing turns public without its author's
choice.

**The name.** The unique on ``strategies.name`` came from 0003 unnamed, so its
name is found in the catalog and never guessed. It becomes ``UNIQUE (author_id,
name)``: two authors may each have a strategy called the same.

**The share leaves the strategy.** ``strategies.allocation_percent`` (nullable
since 0031) and its CHECK are dropped; the share is the subscription's.

**Downgrade.** Refuses when more than one user exists, as 0031's does, since
the global name unique and the single share per strategy only hold for one
author. It restores ``allocation_percent`` (nullable, as at 0032) with its CHECK,
filled from each strategy's author subscription (the latest by ``created_at``),
restores the global name unique, and drops the two columns.
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from strategy_manager.shared.config import get_settings

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "strategies"
_VISIBILITY = "ck_strategies_visibility"
_AUTHOR_NAME = "ux_strategies_author_name"
_SHARE_RANGE = "ck_strategies_allocation_percent_range"
# The name Postgres gives a column-level unique, used when the global one returns.
_NAME_UNIQUE_DEFAULT = "strategies_name_key"


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def _name_unique_name() -> str:
    """The unique constraint on ``strategies (name)`` alone, found in the catalog.
    Raises when there is none: dropping nothing would leave a schema that still
    refuses a second author's strategy of the same name."""
    name = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT c.conname FROM pg_constraint AS c "
                "WHERE c.conrelid = 'strategies'::regclass AND c.contype = 'u' "
                "AND c.conkey = ARRAY[(SELECT a.attnum FROM pg_attribute AS a "
                "WHERE a.attrelid = 'strategies'::regclass AND a.attname = 'name')]"
            )
        )
        .scalar_one_or_none()
    )
    if name is None:
        raise RuntimeError(
            "0033 expected a unique constraint on strategies (name) to drop, and found none"
        )
    return str(name)


def upgrade() -> None:
    secret = get_settings().webhook_secret
    if not secret and _count(f"SELECT count(*) FROM {_TABLE}") > 0:
        raise RuntimeError(
            "0033 gives every existing strategy the hash of the current webhook secret, "
            "and WEBHOOK_SECRET is empty. Set it to the secret the TradingView alerts "
            "carry, then migrate again."
        )

    op.add_column(_TABLE, sa.Column("webhook_secret_hash", sa.Text(), nullable=True))
    if secret:
        op.get_bind().execute(
            sa.text(f"UPDATE {_TABLE} SET webhook_secret_hash = :hash"),
            {"hash": hashlib.sha256(secret.encode("utf-8")).hexdigest()},
        )

    op.add_column(
        _TABLE, sa.Column("visibility", sa.Text(), nullable=False, server_default="PRIVATE")
    )
    op.create_check_constraint(_VISIBILITY, _TABLE, "visibility IN ('PUBLIC', 'PRIVATE')")

    op.drop_constraint(_name_unique_name(), _TABLE, type_="unique")
    op.create_unique_constraint(_AUTHOR_NAME, _TABLE, ["author_id", "name"])

    op.drop_constraint(_SHARE_RANGE, _TABLE, type_="check")
    op.drop_column(_TABLE, "allocation_percent")


def downgrade() -> None:
    users = _count("SELECT count(*) FROM users")
    if users > 1:
        raise RuntimeError(
            "0033's downgrade puts one share and one global name back on each strategy, "
            f"which only holds for one user at most; found {users}. Fix forward instead."
        )

    op.add_column(_TABLE, sa.Column("allocation_percent", sa.Numeric(), nullable=True))
    op.execute(
        """
        UPDATE strategies AS s SET allocation_percent = latest.allocation_percent
          FROM (SELECT DISTINCT ON (sub.strategy_id) sub.strategy_id, sub.allocation_percent
                  FROM subscriptions AS sub
                  JOIN strategies AS st ON st.id = sub.strategy_id AND st.author_id = sub.user_id
                 ORDER BY sub.strategy_id, sub.created_at DESC) AS latest
         WHERE latest.strategy_id = s.id
        """
    )
    op.create_check_constraint(
        _SHARE_RANGE, _TABLE, "allocation_percent > 0 AND allocation_percent <= 100"
    )

    op.drop_constraint(_AUTHOR_NAME, _TABLE, type_="unique")
    op.create_unique_constraint(_NAME_UNIQUE_DEFAULT, _TABLE, ["name"])

    op.drop_constraint(_VISIBILITY, _TABLE, type_="check")
    op.drop_column(_TABLE, "visibility")
    op.drop_column(_TABLE, "webhook_secret_hash")

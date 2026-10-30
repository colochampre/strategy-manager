"""A strategy keeps the last four characters of its webhook secret (multi-user
design decision 25; tasks.md H.1).

Only the secret's SHA-256 is stored, so the panel could not show the secret
masked the way it masks an API key. ``strategies.webhook_secret_last4`` holds the
secret's last four characters, written whenever a secret is issued (the
registration and the regeneration).

**The backfill.** Every existing strategy gets the last four of the current
``Settings.webhook_secret``, the value 0033 hashed for it. They are cut in Python,
as 0033 hashed in Python: the secret never enters SQL text, and no message and no
log line names it or any character of it. With strategies and a setting shorter
than four characters it refuses before anything is written. It also refuses when
a strategy's hash is not the setting's: a secret registered or regenerated since
0033 is the strategy's own, its four cannot be read back from a hash, and the
setting's four would show characters that are not its secret's. The column is
``NOT NULL`` once the backfill has run, with a CHECK on four characters.

**Downgrade.** Drops the column and its CHECK. Nothing else read it.
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from strategy_manager.shared.config import get_settings

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "strategies"
_COLUMN = "webhook_secret_last4"
_CHECK = "ck_strategies_webhook_secret_last4_length"
_LENGTH = 4


def _count(sql: str) -> int:
    return int(op.get_bind().execute(sa.text(sql)).scalar_one())


def upgrade() -> None:
    secret = get_settings().webhook_secret
    if len(secret) < _LENGTH and _count(f"SELECT count(*) FROM {_TABLE}") > 0:
        raise RuntimeError(
            "0034 gives every existing strategy the last four characters of the current "
            f"webhook secret, and WEBHOOK_SECRET has fewer than {_LENGTH}. Set it to the "
            "secret the TradingView alerts carry, then migrate again."
        )

    if len(secret) >= _LENGTH:
        own = int(
            op.get_bind()
            .execute(
                sa.text(f"SELECT count(*) FROM {_TABLE} WHERE webhook_secret_hash <> :hash"),
                {"hash": hashlib.sha256(secret.encode("utf-8")).hexdigest()},
            )
            .scalar_one()
        )
        if own > 0:
            noun = "strategy has" if own == 1 else "strategies have"
            raise RuntimeError(
                f"0034 gives every existing strategy the last four characters of the current "
                f"webhook secret, but {own} {noun} a secret of its own, not WEBHOOK_SECRET "
                "(registered or regenerated since 0033). Its last four cannot be read back "
                "from a hash, so nothing was written."
            )

    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))
    if len(secret) >= _LENGTH:
        op.get_bind().execute(
            sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = :last4"),
            {"last4": secret[-_LENGTH:]},
        )
    # Every row has its four now: the backfill above, or no rows at all (the refusal
    # above leaves no strategy without a secret to cut them from).
    op.alter_column(_TABLE, _COLUMN, nullable=False)
    op.create_check_constraint(_CHECK, _TABLE, f"char_length({_COLUMN}) = {_LENGTH}")


def downgrade() -> None:
    op.drop_constraint(_CHECK, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)

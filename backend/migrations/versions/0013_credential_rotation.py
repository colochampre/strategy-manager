"""Drop ``ux_exchange_credentials_label``: it made key rotation impossible.

Migration ``0010`` set up two constraints on ``exchange_credentials`` whose
intents contradict each other:

- ``ux_exchange_credentials_one_active_per_exchange``, UNIQUE on ``(exchange)``
  WHERE ``is_active`` -- the design. Supersede without deleting: the previous
  row stays, deactivated, so a rotation that turns out to be wrong is a row to
  reactivate rather than a secret that no longer exists anywhere.
- ``ux_exchange_credentials_label``, UNIQUE on ``(exchange, label)`` with no
  partial clause -- which forbids a second row for that pair no matter how
  many of them are inactive.

The second defeats the first. ``scripts/store_pionex_credentials.py`` stores
under a fixed label, so rotating a key raised ``duplicate key value violates
unique constraint`` instead of superseding. Rotation had never worked, despite
three docstrings saying it did, and the vault's own integration tests appearing
to cover it -- they rotated to a NEW label each time, which the script never
does and no caller ever would.

Dropping it rather than making it partial. A partial version would read "at
most one active credential per (exchange, label)", which the per-exchange index
already guarantees more strictly: only one credential per exchange may be
active at all, whatever its label. A constraint that can never fire implies a
guarantee it does not add.

That leaves ``label`` as descriptive metadata rather than an identity, which is
what it always was: it cannot distinguish two concurrently active credentials,
because there can only ever be one.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "exchange_credentials"
_CONSTRAINT = "ux_exchange_credentials_label"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")


def downgrade() -> None:
    """Refuses while any superseded row would violate the restored constraint.

    Those rows are the audit trail of every key this system has ever held.
    Recreating the constraint by deleting them would destroy exactly what it
    was keeping, and silently.
    """
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT count(*) FROM (SELECT exchange, label FROM {_TABLE} "  # noqa: S608
                "GROUP BY exchange, label HAVING count(*) > 1) AS d"
            )
        )
        .scalar_one()
    )
    if duplicates:
        raise RuntimeError(
            f"{duplicates} (exchange, label) pair(s) have more than one row, "
            "which is the credential rotation history this constraint used to "
            "forbid. Restoring it means deleting superseded credentials. Do "
            "that deliberately by hand if you really want it."
        )

    op.create_unique_constraint(_CONSTRAINT, _TABLE, ["exchange", "label"])

"""``exchange_credentials``: record how each fact about a key was established
(design.md, "Addendum: key policy after probe P6", section B; tasks.md unit 6a,
owner decisions 24 and 30).

**The principle: the record says how each fact was established, and never
claims more than was.** Neither venue lets this system read everything it needs.
Bybit reports ``readOnly`` and ``permissions.Wallet``, so those facts are
``VERIFIED``. Binance reveals neither (SAPI answers 403 from the VPS, and the
account-level ``canTrade`` / ``canWithdraw`` were true on a key that could do
neither), so the owner confirms them and the fact is ``OWNER_CONFIRMED``, with
the moment they said so. A row sealed before this migration has no record at
all: ``UNRECORDED``.

Columns added:

- ``trade_capable``            boolean NOT NULL. What the system acts on.
- ``trade_capability_source``  text NOT NULL. VERIFIED / OWNER_CONFIRMED / UNRECORDED.
- ``trade_confirmed_at``       timestamptz NULL. When the owner confirmed "Enable Futures".
- ``withdraw_check``           text NOT NULL. How "this key cannot withdraw" was established.
- ``withdraw_confirmed_at``    timestamptz NULL. When the owner confirmed "withdrawals disabled".
- ``validated_at``             timestamptz NULL. When the save-time live read passed.
- ``internal_transfer``        boolean NULL. Bybit ``AccountTransfer`` present; NULL is unknown.

There is deliberately NO ``permissions`` column. A raw payload carries the
owner's whitelisted IPs, the user id and the KYC region; storing it would keep
that data at rest with no reader. The derived facts above are the smaller and
safer record.

**The backfill.** Every existing row (production holds one active key each for
binance, bybit and pionex, plus any history) becomes ``trade_capable = true``
with both sources ``UNRECORDED`` and every timestamp and ``internal_transfer``
NULL. Honest, because:

- ``true`` is what the system already acts on. Every one of those rows was
  sealed by a ``store_*_credentials.py`` that refused a key it could not see
  trading, and the worker signs with them today. ``false`` would assert
  something nobody knows.
- ``UNRECORDED`` says what is true: no record exists of how the key was
  checked. A migration can neither decrypt a key nor call a venue, so it must
  not write ``VERIFIED``; and the owner has confirmed nothing, so it must not
  write ``OWNER_CONFIRMED`` either, whose timestamp would then be
  indistinguishable from a real one.

The columns are added ``DEFAULT true`` / ``DEFAULT 'UNRECORDED'`` to do the
backfill in the same statement, the CHECKs are created, and then the defaults
are DROPPED: a writer that forgets to state a fact fails instead of guessing.

**The CHECKs** (all ``ck_exchange_credentials_*``; the domain's ``KeyFacts``
refuses the same states for 2 to 4, and the table alone enforces 5 and 6
because only the row knows its exchange):

1. ``sources_known``                 both source columns are one of the three values.
2. ``confirmation_has_timestamp``    an OWNER_CONFIRMED source and its timestamp exist
                                     together, for trade and for withdraw.
3. ``confirmed_trade_is_capable``    the owner confirms a capability, never an incapability.
4. ``recorded_or_legacy``            fully recorded or fully legacy, and ``validated_at``
                                     is NULL exactly when the facts are UNRECORDED.
5. ``binance_not_verified``          a Binance row cannot claim a verification the venue
                                     does not allow. If SAPI ever becomes reachable, a
                                     new migration relaxes this; a policy change is a
                                     migration.
6. ``bybit_not_owner_confirmed``     Bybit is verified server-side; an owner confirmation
                                     there would mean the code took the wrong branch.

**The downgrade refusal.** Dropping the columns would erase who vouched for a
key and could make a read-only key look trade-capable, the same reasoning as
0025 and 0026. It refuses while any row is not in the backfill shape and names
each count. After the first save through Settings the refusal is permanent, by
design. There is no force flag: the owner deletes rows by hand if that is
really wanted (the 0013 precedent).

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "exchange_credentials"

_SOURCES_KNOWN = "ck_exchange_credentials_sources_known"
_CONFIRMATION_HAS_TIMESTAMP = "ck_exchange_credentials_confirmation_has_timestamp"
_CONFIRMED_TRADE_IS_CAPABLE = "ck_exchange_credentials_confirmed_trade_is_capable"
_RECORDED_OR_LEGACY = "ck_exchange_credentials_recorded_or_legacy"
_BINANCE_NOT_VERIFIED = "ck_exchange_credentials_binance_not_verified"
_BYBIT_NOT_OWNER_CONFIRMED = "ck_exchange_credentials_bybit_not_owner_confirmed"

_CHECKS: list[tuple[str, str]] = [
    (
        _SOURCES_KNOWN,
        "trade_capability_source IN ('VERIFIED', 'OWNER_CONFIRMED', 'UNRECORDED') "
        "AND withdraw_check IN ('VERIFIED', 'OWNER_CONFIRMED', 'UNRECORDED')",
    ),
    (
        _CONFIRMATION_HAS_TIMESTAMP,
        "(trade_capability_source = 'OWNER_CONFIRMED') = (trade_confirmed_at IS NOT NULL) "
        "AND (withdraw_check = 'OWNER_CONFIRMED') = (withdraw_confirmed_at IS NOT NULL)",
    ),
    (
        _CONFIRMED_TRADE_IS_CAPABLE,
        "trade_capability_source <> 'OWNER_CONFIRMED' OR trade_capable",
    ),
    (
        _RECORDED_OR_LEGACY,
        "(trade_capability_source = 'UNRECORDED') = (withdraw_check = 'UNRECORDED') "
        "AND (validated_at IS NULL) = (withdraw_check = 'UNRECORDED')",
    ),
    (
        _BINANCE_NOT_VERIFIED,
        "exchange <> 'binance' OR "
        "(trade_capability_source <> 'VERIFIED' AND withdraw_check <> 'VERIFIED')",
    ),
    (
        _BYBIT_NOT_OWNER_CONFIRMED,
        "exchange <> 'bybit' OR "
        "(trade_capability_source <> 'OWNER_CONFIRMED' AND withdraw_check <> 'OWNER_CONFIRMED')",
    ),
]

# Columns that carry a backfill default only for the length of this migration.
_DEFAULTED = ("trade_capable", "trade_capability_source", "withdraw_check")


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("trade_capable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "trade_capability_source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'UNRECORDED'"),
        ),
    )
    op.add_column(_TABLE, sa.Column("trade_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column(
        _TABLE,
        sa.Column(
            "withdraw_check", sa.Text(), nullable=False, server_default=sa.text("'UNRECORDED'")
        ),
    )
    op.add_column(_TABLE, sa.Column("withdraw_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("validated_at", sa.DateTime(timezone=True)))
    op.add_column(_TABLE, sa.Column("internal_transfer", sa.Boolean()))

    for name, condition in _CHECKS:
        op.create_check_constraint(name, _TABLE, condition)

    for column in _DEFAULTED:
        op.alter_column(_TABLE, column, server_default=None)


def downgrade() -> None:
    bind: Connection = op.get_bind()

    def count(where: str) -> int:
        return bind.execute(
            sa.text(f"SELECT count(*) FROM {_TABLE} WHERE {where}")  # noqa: S608
        ).scalar_one()

    incapable = count("trade_capable = false")
    trade_recorded = count("trade_capability_source <> 'UNRECORDED'")
    withdraw_recorded = count("withdraw_check <> 'UNRECORDED'")
    transfer_recorded = count("internal_transfer IS NOT NULL")

    if incapable or trade_recorded or withdraw_recorded or transfer_recorded:
        raise RuntimeError(
            "Refusing to downgrade 0027_credential_snapshot: exchange_credentials holds "
            "facts that cannot be recomputed once dropped: "
            f"{incapable} row(s) with trade_capable = false, "
            f"{trade_recorded} row(s) whose trade_capability_source is not UNRECORDED, "
            f"{withdraw_recorded} row(s) whose withdraw_check is not UNRECORDED, "
            f"{transfer_recorded} row(s) with a recorded internal_transfer. "
            "Dropping the columns would erase who vouched for a key, and could make a "
            "read-only key look trade-capable (0025/0026 precedent). This downgrade "
            "offers no force flag; delete the rows by hand if that is really wanted "
            "(0013 precedent)."
        )

    for name, _ in reversed(_CHECKS):
        op.drop_constraint(name, _TABLE, type_="check")
    for column in (
        "internal_transfer",
        "validated_at",
        "withdraw_confirmed_at",
        "withdraw_check",
        "trade_confirmed_at",
        "trade_capability_source",
        "trade_capable",
    ):
        op.drop_column(_TABLE, column)

"""The identity given at sign-up and the acceptance record
(openspec/changes/public-site, LS2-LS5).

**On ``users``**, six nullable columns: first name, last name, CUIT, country, and
when the user declared being 18 or older and that their data is true. Nothing is
backfilled: the existing users have given none of it, and meet the sign-up form on
their next visit (LS2). Three CHECKs hold what the application already refuses:

- ``ck_users_profile_whole``: the six are all set or all empty, so no half-given
  identity can read as a complete one;
- ``ck_users_cuit_shape``: eleven ASCII digits (the check digit is the
  application's: SQL could compute it, but one rule in two places drifts);
- ``ck_users_country_served``: Argentina only (LS1).

``ck_users_deleted_names_nobody`` now also requires a deleted row to hold no
identity. LQ6 asks the lawyer whether it may be kept for a term after deletion;
until then deleting the account erases it, as the published policy says.

**``legal_acceptances``**, one row per acceptance: who, which terms version, which
privacy version, when (LS3). It is evidence, so it is append-only like the ledger,
by the same two triggers: a row trigger refuses UPDATE and DELETE and a statement
trigger refuses TRUNCATE, because REVOKE does not bind the superuser this app
connects as. A deleted account's rows stay, as its ledger does.

**Downgrade.** Refused while any acceptance is recorded: it would destroy the
record. Otherwise it drops the table and the columns and restores 0045's CHECK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USERS = "users"
_ACCEPTANCES = "legal_acceptances"
_TEXT_COLUMNS = ("first_name", "last_name", "cuit", "country")
_DECLARATION_COLUMNS = ("adult_declared_at", "truthful_declared_at")
_PROFILE_COLUMNS = _TEXT_COLUMNS + _DECLARATION_COLUMNS
_DELETED_CHECK = "ck_users_deleted_names_nobody"
_DELETED_AT_0045 = (
    "deleted_at IS NULL OR (display_name IS NULL AND email = 'deleted-' || id::text || '@invalid')"
)
_DELETED_AT_0046 = (
    "deleted_at IS NULL OR (display_name IS NULL "
    "AND email = 'deleted-' || id::text || '@invalid' "
    "AND first_name IS NULL AND last_name IS NULL AND cuit IS NULL)"
)
_APPEND_ONLY_FUNCTION = "fn_legal_acceptances_append_only"


def upgrade() -> None:
    for column in _TEXT_COLUMNS:
        op.add_column(_USERS, sa.Column(column, sa.Text(), nullable=True))
    for column in _DECLARATION_COLUMNS:
        op.add_column(_USERS, sa.Column(column, sa.DateTime(timezone=True), nullable=True))

    all_set = " AND ".join(f"{column} IS NOT NULL" for column in _PROFILE_COLUMNS)
    all_empty = " AND ".join(f"{column} IS NULL" for column in _PROFILE_COLUMNS)
    op.create_check_constraint("ck_users_profile_whole", _USERS, f"({all_set}) OR ({all_empty})")
    op.create_check_constraint("ck_users_cuit_shape", _USERS, "cuit ~ '^[0-9]{11}$'")
    op.create_check_constraint("ck_users_country_served", _USERS, "country = 'AR'")

    op.drop_constraint(_DELETED_CHECK, _USERS, type_="check")
    op.create_check_constraint(_DELETED_CHECK, _USERS, _DELETED_AT_0046)

    op.create_table(
        _ACCEPTANCES,
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("terms_version", sa.Text(), nullable=False),
        sa.Column("privacy_version", sa.Text(), nullable=False),
        sa.Column(
            "accepted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_legal_acceptances_user"),
    )
    op.create_index("ix_legal_acceptances_user_accepted", _ACCEPTANCES, ["user_id", "accepted_at"])

    op.execute(
        f"""
        CREATE FUNCTION {_APPEND_ONLY_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'legal_acceptances is append-only: % is not permitted', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_legal_acceptances_no_update_delete
            BEFORE UPDATE OR DELETE ON {_ACCEPTANCES}
            FOR EACH ROW EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_legal_acceptances_no_truncate
            BEFORE TRUNCATE ON {_ACCEPTANCES}
            FOR EACH STATEMENT EXECUTE FUNCTION {_APPEND_ONLY_FUNCTION}();
        """
    )


def downgrade() -> None:
    row_count = op.get_bind().execute(sa.text(f"SELECT count(*) FROM {_ACCEPTANCES}")).scalar_one()
    if row_count:
        raise RuntimeError(
            f"Refusing to downgrade 0046: {_ACCEPTANCES} holds {row_count} row(s). "
            "They record who accepted which terms and when, and this data cannot be rebuilt."
        )
    op.execute(f"DROP TRIGGER IF EXISTS trg_legal_acceptances_no_truncate ON {_ACCEPTANCES}")
    op.execute(f"DROP TRIGGER IF EXISTS trg_legal_acceptances_no_update_delete ON {_ACCEPTANCES}")
    op.execute(f"DROP FUNCTION IF EXISTS {_APPEND_ONLY_FUNCTION}()")
    op.drop_table(_ACCEPTANCES)

    op.drop_constraint(_DELETED_CHECK, _USERS, type_="check")
    op.create_check_constraint(_DELETED_CHECK, _USERS, _DELETED_AT_0045)
    for name in ("ck_users_country_served", "ck_users_cuit_shape", "ck_users_profile_whole"):
        op.drop_constraint(name, _USERS, type_="check")
    for column in reversed(_PROFILE_COLUMNS):
        op.drop_column(_USERS, column)

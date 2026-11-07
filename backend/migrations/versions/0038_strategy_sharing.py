"""Sharing a strategy off the public list, by a link or by single-use invitation
codes (multi-user decision 41; tasks.md K.1).

**The link.** ``strategies.visibility`` takes ``LINK`` beside ``PUBLIC`` and
``PRIVATE``, and ``strategies.share_token`` holds the link's token: set exactly
while the strategy is ``LINK`` (``ck_strategies_share_token_iff_link``), so leaving
``LINK`` kills the link and coming back needs a new one. It is shaped as
``secrets.token_urlsafe(32)`` writes one, 43 URL-safe characters, and no two
strategies share one. It is stored readable, so the author's aside can always show
it (decision 41). Existing strategies keep their visibility and get no token.

**The codes.** ``invite_codes`` holds a strategy's codes. Never the code: its
SHA-256 in lower-case hex, and ``hint``, its last four characters in Crockford
base32, which is what the author's list shows. A code expires after it was made, is
revoked or redeemed but never both, and its redemption is recorded whole: who, when
and the seat it made, one code per seat. Who used which code stays here for audit;
nothing shows it (decision 41). A strategy's deletion takes its codes with it, as
it takes its subscriptions (``fk_subscriptions_strategy`` cascades), and so does
the deletion of the seat a code made.

**Downgrade.** Refuses while a strategy is ``LINK`` or any code exists, naming
which: dropping them would end a shared link and erase who entered by which code,
without a word. With neither, it drops the table and the column and restores
``0037``'s visibility CHECK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRATEGIES = "strategies"
_VISIBILITY = "ck_strategies_visibility"
_TOKEN = "share_token"
_TOKEN_IFF_LINK = "ck_strategies_share_token_iff_link"
_TOKEN_SHAPE = "ck_strategies_share_token_shape"
_TOKEN_UNIQUE = "ux_strategies_share_token"

_CODES = "invite_codes"


def upgrade() -> None:
    op.drop_constraint(_VISIBILITY, _STRATEGIES, type_="check")
    op.create_check_constraint(
        _VISIBILITY, _STRATEGIES, "visibility IN ('PUBLIC', 'LINK', 'PRIVATE')"
    )
    op.add_column(_STRATEGIES, sa.Column(_TOKEN, sa.Text(), nullable=True))
    op.create_check_constraint(
        _TOKEN_IFF_LINK, _STRATEGIES, f"(visibility = 'LINK') = ({_TOKEN} IS NOT NULL)"
    )
    op.create_check_constraint(
        _TOKEN_SHAPE, _STRATEGIES, f"{_TOKEN} IS NULL OR {_TOKEN} ~ '^[A-Za-z0-9_-]{{43}}$'"
    )
    op.create_index(_TOKEN_UNIQUE, _STRATEGIES, [_TOKEN], unique=True)

    op.create_table(
        _CODES,
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("strategy_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_by", PGUUID(as_uuid=True), nullable=True),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_id", PGUUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["strategy_id"], ["strategies.id"], name="fk_invite_codes_strategy", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["redeemed_by"], ["users.id"], name="fk_invite_codes_redeemed_by"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name="fk_invite_codes_subscription",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name="ck_invite_codes_code_hash_shape"),
        sa.CheckConstraint(
            "hint ~ '^[0-9A-HJKMNP-TV-Z]{4}$'", name="ck_invite_codes_hint_shape"
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_invite_codes_expiry_after_creation"
        ),
        sa.CheckConstraint(
            "(redeemed_by IS NULL) = (redeemed_at IS NULL) "
            "AND (redeemed_at IS NULL) = (subscription_id IS NULL)",
            name="ck_invite_codes_redemption_whole",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR redeemed_at IS NULL",
            name="ck_invite_codes_revoked_or_redeemed",
        ),
    )
    op.create_index("ux_invite_codes_code_hash", _CODES, ["code_hash"], unique=True)
    op.create_index("ux_invite_codes_subscription", _CODES, ["subscription_id"], unique=True)
    op.create_index("ix_invite_codes_strategy_id", _CODES, ["strategy_id"])


def downgrade() -> None:
    connection = op.get_bind()
    linked = connection.execute(
        sa.text("SELECT count(*) FROM strategies WHERE visibility = 'LINK'")
    ).scalar_one()
    codes = connection.execute(sa.text(f"SELECT count(*) FROM {_CODES}")).scalar_one()  # noqa: S608
    refusals = []
    if linked:
        refusals.append(f"{linked} strategy(ies) shared by a link")
    if codes:
        refusals.append(f"{codes} invitation code(s)")
    if refusals:
        raise RuntimeError(
            "0038 downgrade refused: " + " and ".join(refusals) + " would be dropped. "
            "Turn those strategies PUBLIC or PRIVATE and delete the codes first, on purpose."
        )

    op.drop_table(_CODES)
    op.drop_index(_TOKEN_UNIQUE, table_name=_STRATEGIES)
    op.drop_constraint(_TOKEN_SHAPE, _STRATEGIES, type_="check")
    op.drop_constraint(_TOKEN_IFF_LINK, _STRATEGIES, type_="check")
    op.drop_column(_STRATEGIES, _TOKEN)
    op.drop_constraint(_VISIBILITY, _STRATEGIES, type_="check")
    op.create_check_constraint(_VISIBILITY, _STRATEGIES, "visibility IN ('PUBLIC', 'PRIVATE')")

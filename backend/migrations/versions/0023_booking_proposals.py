"""``booking_proposals`` -- the frozen snapshot a human approves or rejects
before a venue-originated close reaches the ledger (design.md § 3
"``booking_proposals`` -- migration 0023"; spec: venue-close-booking
§ "Proposal Prepared From a Frozen Snapshot, At Most One Pending").

A proposal is evidence shown to a human, not a working row the application
mutates freely. Its frozen columns (``discrepancy_id`` through ``created_at``
below) are written exactly once, by ``PrepareBooking``, and never touched
again -- the same "frozen snapshot" discipline
``reconciliation_discrepancies`` (migration 0020) already gives its own
observed columns. Only ``state``, ``decided_at``, ``decided_by``,
``decision_reason`` and ``execution_attempt_id`` change, and each changes
exactly once, by ``ApproveBooking``/``RejectBooking``/``ExpireBookingProposals``.

``discrepancy_id`` carries NO ``ON DELETE CASCADE`` -- the same argument
0020 makes for its own FK to ``capital_pools``: a proposal is a record that
this exact snapshot was shown to a human and (if approved) acted on, and
deleting the discrepancy it was prepared from must not make that record
disappear with it. The composite FK to ``capital_pools`` follows the exact
``(exchange, venue, settlement_currency)`` column order 0020 already
established as the convention for every table pointing at that key.
``prepared_by_job_id`` holds a ``jobs.id`` value but carries NO foreign key,
for the identical reason 0020's ``*_scan_id`` columns do not: jobs are
pruned, and a proposal must outlive the job that prepared it.

``kind`` is restricted, by CHECK, to the two BOOKABLE verdicts of
``reconciliation_discrepancies``' own four-verdict ladder
(``ATTRIBUTABLE_SINGLE_ALLOCATION``, ``ATTRIBUTABLE_FULL_CLOSE``) --
``AMBIGUOUS_PARTIAL_REDUCE`` and ``NO_MATCHING_ALLOCATION`` can never be
proposed, so the table itself cannot hold one, not merely the application
that writes it (design.md § 5, § "domain/booking.py").

``fills`` is a JSONB array, frozen at prepare, ordered by
``(filled_at ASC, exchange_fill_id ASC)`` with the ``(len(id), id)`` tiebreak
recorded in design.md § 3. Every number in every element is a STRING -- the
same rule ``_amount()`` already enforces on the wire, because a JSON number
has already lost the precision an append-only ledger downstream depends on.
No child ``booking_proposal_fills`` table: the snapshot is an immutable blob
shown once to a human and never joined, filtered or aggregated (design.md's
own rejected alternative, § 3).

``ux_booking_proposals_pending_per_discrepancy`` is this table's idempotency:
at most one PENDING proposal may exist per discrepancy, so a second
``PrepareBooking`` sweep over the same still-open discrepancy writes nothing
new. ``ix_booking_proposals_pending`` serves the list endpoint and the expiry
sweep, both of which only ever look at PENDING rows. Neither partial index
serves the REJECTED-suppression lookup (design.md § 11), which reads every
state for a given discrepancy regardless of its current state -- that lookup
is ``ix_booking_proposals_discrepancy``, a full (non-partial) index.

The three state CHECKs encode exactly the state machine design.md § 3
states in prose: a non-PENDING row always carries a decision timestamp; a
REJECTED row always carries a non-blank reason (``btrim(coalesce(...))``
catches both a NULL and an all-whitespace string); and
``execution_attempt_id`` is populated if and only if the row is APPROVED.

``downgrade()`` DROPs unconditionally, with NO refusal clause -- the
deliberate asymmetry with 0022's guarded downgrade. A ``booking_proposals``
row is not money: it is a proposal, shown to a human, that money may or may
not have moved because of. The real consequence of an APPROVED row lives in
``execution_attempts``/``ledger_entries``, and 0022's own guard already
protects that history from disappearing. Dropping this table loses only the
paper trail of what was proposed and decided, never the ledger itself.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "booking_proposals"
_POOL_COLUMNS = ["exchange", "venue", "settlement_currency"]

# The two BOOKABLE verdicts of reconciliation_discrepancies' four-verdict
# ladder (migration 0020). AMBIGUOUS_PARTIAL_REDUCE and NO_MATCHING_ALLOCATION
# are deliberately absent -- design.md § 5.
_BOOKABLE_KINDS = (
    "kind IN ('ATTRIBUTABLE_SINGLE_ALLOCATION','ATTRIBUTABLE_FULL_CLOSE')"
)
_SIDE_CHECK = "side IN ('BUY','SELL')"
_QUANTITY_POSITIVE = "quantity > 0"

# The three state-machine CHECKs, design.md § 3 verbatim.
_DECIDED_AT_REQUIRED = "state = 'PENDING' OR decided_at IS NOT NULL"
_REJECTED_NEEDS_REASON = (
    "state <> 'REJECTED' OR btrim(coalesce(decision_reason, '')) <> ''"
)
_EXECUTION_ATTEMPT_ONLY_APPROVED = "state = 'APPROVED' OR execution_attempt_id IS NULL"

# Added in review beyond design.md § 3, each closing a way to fail without a
# log line. A misspelt state satisfies the three CHECKs above vacuously and
# drops out of both partial indexes, so the proposal silently stops being
# listed and stops blocking a second one. An empty `fills` can only
# come from a bug: match_fills refuses zero unrecorded fills.
_STATE_CHECK = "state IN ('PENDING','APPROVED','REJECTED','SUPERSEDED','EXPIRED')"
_FILLS_NONEMPTY_ARRAY = "jsonb_typeof(fills) = 'array' AND jsonb_array_length(fills) > 0"
# Exactly one observed allocation, and it is the one being booked. A
# flat venue over SEVERAL allocations is ATTRIBUTABLE_FULL_CLOSE too, but
# one booking can attribute a close to only one allocation without an
# invented split, which the owner ruled out.
_SINGLE_ALLOCATION = (
    "cardinality(observed_allocation_ids) = 1 "
    "AND observed_allocation_ids[1] = allocation_id"
)

_PENDING_UNIQUE_INDEX = "ux_booking_proposals_pending_per_discrepancy"
_PENDING_LOOKUP_INDEX = "ix_booking_proposals_pending"
_DISCREPANCY_LOOKUP_INDEX = "ix_booking_proposals_discrepancy"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # -- Frozen at prepare, never updated again. --
        sa.Column("discrepancy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("venue", sa.Text(), nullable=False),
        sa.Column("settlement_currency", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("allocation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(38, 18), nullable=False),
        sa.Column("observed_venue_net_base", sa.Numeric(38, 18), nullable=False),
        sa.Column("observed_ledger_net_base", sa.Numeric(38, 18), nullable=False),
        sa.Column(
            "observed_allocation_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("fills", postgresql.JSONB(), nullable=False),
        sa.Column("client_order_id", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # jobs.id -- deliberately no FK, same reasoning as 0020's *_scan_id.
        sa.Column("prepared_by_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # -- Mutable, exactly once. --
        sa.Column("state", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("execution_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["discrepancy_id"],
            ["reconciliation_discrepancies.id"],
            name="fk_booking_proposals_discrepancy",
            # Deliberately no ON DELETE CASCADE -- see module docstring.
        ),
        sa.ForeignKeyConstraint(
            _POOL_COLUMNS,
            [f"capital_pools.{column}" for column in _POOL_COLUMNS],
            name="fk_booking_proposals_capital_pool",
        ),
        sa.ForeignKeyConstraint(
            ["allocation_id"],
            ["reservations.id"],
            name="fk_booking_proposals_allocation",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategies.id"],
            name="fk_booking_proposals_strategy",
        ),
        sa.ForeignKeyConstraint(
            ["execution_attempt_id"],
            ["execution_attempts.id"],
            name="fk_booking_proposals_execution_attempt",
            # Deliberately no ON DELETE CASCADE -- an APPROVED proposal must
            # not lose the pointer to the attempt it caused.
        ),
        sa.CheckConstraint(_BOOKABLE_KINDS, name="ck_booking_proposals_kind"),
        sa.CheckConstraint(_SIDE_CHECK, name="ck_booking_proposals_side"),
        sa.CheckConstraint(_QUANTITY_POSITIVE, name="ck_booking_proposals_quantity_positive"),
        sa.CheckConstraint(_DECIDED_AT_REQUIRED, name="ck_booking_proposals_decided_at"),
        sa.CheckConstraint(
            _REJECTED_NEEDS_REASON, name="ck_booking_proposals_rejected_reason"
        ),
        sa.CheckConstraint(
            _EXECUTION_ATTEMPT_ONLY_APPROVED,
            name="ck_booking_proposals_execution_attempt_only_approved",
        ),
        sa.CheckConstraint(_STATE_CHECK, name="ck_booking_proposals_state"),
        sa.CheckConstraint(
            _FILLS_NONEMPTY_ARRAY, name="ck_booking_proposals_fills_nonempty_array"
        ),
        sa.CheckConstraint(_SINGLE_ALLOCATION, name="ck_booking_proposals_single_allocation"),
    )
    op.create_index(
        _PENDING_UNIQUE_INDEX,
        _TABLE,
        ["discrepancy_id"],
        unique=True,
        postgresql_where=sa.text("state = 'PENDING'"),
    )
    op.create_index(
        _PENDING_LOOKUP_INDEX,
        _TABLE,
        ["state", "expires_at"],
        postgresql_where=sa.text("state = 'PENDING'"),
    )
    op.create_index(_DISCREPANCY_LOOKUP_INDEX, _TABLE, ["discrepancy_id"])


def downgrade() -> None:
    # Unconditional -- no refusal clause. See module docstring for the
    # deliberate asymmetry with 0022's guarded downgrade.
    op.drop_index(_DISCREPANCY_LOOKUP_INDEX, table_name=_TABLE)
    op.drop_index(_PENDING_LOOKUP_INDEX, table_name=_TABLE)
    op.drop_index(_PENDING_UNIQUE_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)

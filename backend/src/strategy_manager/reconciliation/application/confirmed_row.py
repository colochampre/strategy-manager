"""One way to build the ``ConfirmedRow`` the ``needs_owner`` rule reads, shared
by ``AnnounceNeedsOwner`` (the worker's alert) and ``ReadConfirmed`` (the
panel's route), so the alert and the view can never sort the same row two
ways (design.md PR 15 addendum § D)."""

from collections.abc import Sequence

from strategy_manager.reconciliation.application.ports import DiscrepancyRecord
from strategy_manager.reconciliation.domain.attention import ConfirmedRow
from strategy_manager.reconciliation.domain.discrepancy import Observation


def to_confirmed_row(
    record: DiscrepancyRecord, approved_observations: Sequence[Observation]
) -> ConfirmedRow:
    return ConfirmedRow(
        status=record.status,
        resolved=record.resolved_at is not None,
        observation=Observation(record.kind, record.venue_net_base, record.ledger_net_base),
        open_allocation_count=len(record.open_allocation_ids),
        confirmed_at=record.confirmed_at,
        approved_observations=approved_observations,
    )

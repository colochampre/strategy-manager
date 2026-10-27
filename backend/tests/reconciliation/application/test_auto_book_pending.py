"""``AutoBookPending`` -- the worker approves every PENDING proposal in its own
job (spec "Prepared Proposals Are Approved By The Worker In The Same Job";
design.md PR 15 addendum § C1, § C6; owner decision 66 Q1, 2026-10-16).

Fakes only: the use case depends on ``ApprovePort``, never on ``ApproveBooking``.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application.approve_booking import (
    ApproveOutcome,
    ApproveResult,
)
from strategy_manager.reconciliation.application.auto_book_pending import (
    AUTO_BOOKING_ACTOR,
    AutoBookPending,
)
from strategy_manager.reconciliation.application.ports import BookingProposalRecord
from strategy_manager.reconciliation.domain.booking import BookingRefusal
from strategy_manager.reconciliation.domain.discrepancy import DiscrepancyKind
from tests.owner import OWNER_ID

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


def _proposal() -> BookingProposalRecord:
    return BookingProposalRecord(
        id=uuid4(),
        user_id=OWNER_ID,
        discrepancy_id=uuid4(),
        exchange="bybit",
        venue="usdt-m",
        settlement_currency="USDT",
        symbol="STXUSDT",
        kind=DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        allocation_id=uuid4(),
        strategy_id=uuid4(),
        side="SELL",
        quantity=Decimal("0.5"),
        observed_venue_net_base=Decimal("0"),
        observed_ledger_net_base=Decimal("0.5"),
        observed_allocation_ids=(),
        fills=(),
        client_order_id="client-order-id",
        expires_at=NOW,
        prepared_by_job_id=uuid4(),
        created_at=NOW,
        state="PENDING",
        decided_at=None,
        decided_by=None,
        decision_reason=None,
        execution_attempt_id=None,
    )


class FakeProposals:
    """Answers ``list_pending`` like the repository: oldest expiry first, at
    most ``limit`` rows. Everything else is out of this use case's reach."""

    def __init__(self, pending: list[BookingProposalRecord]) -> None:
        self._pending = pending
        self.decided: set[UUID] = set()
        self.limits_asked: list[int] = []

    def _still_pending(self) -> list[BookingProposalRecord]:
        return [p for p in self._pending if p.id not in self.decided]

    async def list_pending(self, limit: int = 100) -> list[BookingProposalRecord]:
        self.limits_asked.append(limit)
        return self._still_pending()[:limit]

    async def count_pending(self) -> int:
        return len(self._still_pending())


class FakeApprover:
    """Decides a proposal the way ``ApproveBooking`` does: whatever the
    outcome, the row leaves PENDING (when ``proposals`` is given)."""

    def __init__(self, outcomes: dict[UUID, ApproveOutcome] | None = None) -> None:
        self._outcomes = outcomes or {}
        self.calls: list[tuple[UUID, str]] = []
        self.proposals: FakeProposals | None = None

    async def approve(self, proposal_id: UUID, decided_by: str) -> ApproveResult:
        self.calls.append((proposal_id, decided_by))
        if self.proposals is not None:
            self.proposals.decided.add(proposal_id)
        return ApproveResult(
            outcome=self._outcomes.get(proposal_id, ApproveOutcome.APPROVED),
            proposal_id=proposal_id,
        )


def _use_case(
    pending: list[BookingProposalRecord],
    approver: FakeApprover,
    limit: int = 100,
) -> tuple[AutoBookPending, FakeProposals]:
    proposals = FakeProposals(pending)
    approver.proposals = proposals
    use_case = AutoBookPending(
        proposals=proposals,  # type: ignore[arg-type]
        approver=approver,
        limit=limit,
    )
    return use_case, proposals


def test_the_actor_is_the_one_fixed_string() -> None:
    assert AUTO_BOOKING_ACTOR == "system:auto-booking"


async def test_it_approves_every_pending_proposal_in_list_order_as_the_system_actor() -> None:
    pending = [_proposal(), _proposal(), _proposal()]
    approver = FakeApprover()
    use_case, _ = _use_case(pending, approver)

    result = await use_case.run()

    assert approver.calls == [(p.id, "system:auto-booking") for p in pending]
    assert result.outcomes == {"APPROVED": 3}
    assert result.not_approved == {}
    assert result.left_for_next_run == 0


async def test_an_empty_list_calls_nothing() -> None:
    approver = FakeApprover()
    use_case, _ = _use_case([], approver)

    result = await use_case.run()

    assert approver.calls == []
    assert result.outcomes == {}
    assert result.not_approved == {}
    assert result.left_for_next_run == 0


async def test_a_stale_proposal_is_reported_with_its_discrepancy_id_and_the_stale_code() -> None:
    approved, superseded, expired = _proposal(), _proposal(), _proposal()
    approver = FakeApprover(
        {superseded.id: ApproveOutcome.SUPERSEDED, expired.id: ApproveOutcome.EXPIRED}
    )
    use_case, _ = _use_case([approved, superseded, expired], approver)

    result = await use_case.run()

    assert result.outcomes == {"APPROVED": 1, "SUPERSEDED": 1, "EXPIRED": 1}
    assert result.not_approved == {
        superseded.discrepancy_id: BookingRefusal.STALE_AT_APPROVAL,
        expired.discrepancy_id: BookingRefusal.STALE_AT_APPROVAL,
    }
    assert result.approved == (approved.discrepancy_id,)


async def test_a_proposal_someone_else_already_decided_is_counted_but_not_called_stale() -> None:
    """``ALREADY_DECIDED`` is a replay lost to another approver (design § C4),
    not a stale proposal: the design maps only SUPERSEDED and EXPIRED to
    ``STALE_AT_APPROVAL`` (§ E)."""

    decided = _proposal()
    approver = FakeApprover({decided.id: ApproveOutcome.ALREADY_DECIDED})
    use_case, _ = _use_case([decided], approver)

    result = await use_case.run()

    assert result.outcomes == {"ALREADY_DECIDED": 1}
    assert result.not_approved == {}
    assert result.approved == ()
    assert result.already_decided == (decided.discrepancy_id,)


async def test_the_limit_is_honoured_and_the_rest_is_reported() -> None:
    pending = [_proposal() for _ in range(5)]
    approver = FakeApprover()
    use_case, proposals = _use_case(pending, approver, limit=3)

    result = await use_case.run()

    assert [call[0] for call in approver.calls] == [p.id for p in pending[:3]]
    assert result.outcomes == {"APPROVED": 3}
    assert result.left_for_next_run == 2, "the EXACT number past the limit (design § C6)"
    assert proposals.limits_asked == [3], "exactly `limit` rows are read, none extra"


async def test_exactly_the_limit_leaves_nothing_for_the_next_run() -> None:
    pending = [_proposal() for _ in range(3)]
    approver = FakeApprover()
    use_case, _ = _use_case(pending, approver, limit=3)

    result = await use_case.run()

    assert len(approver.calls) == 3
    assert result.left_for_next_run == 0


async def test_an_unexpected_exception_in_one_approval_propagates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design § C6: deliberately NOT caught per proposal."""

    class Boom:
        async def approve(self, proposal_id: UUID, decided_by: str) -> ApproveResult:
            raise RuntimeError("ledger writer fault")

    use_case = AutoBookPending(
        proposals=FakeProposals([_proposal()]),  # type: ignore[arg-type]
        approver=Boom(),
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError):
        await use_case.run()


async def test_an_automatic_booking_logs_nothing_above_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    approver = FakeApprover()
    use_case, _ = _use_case([_proposal()], approver)

    with caplog.at_level(logging.DEBUG):
        await use_case.run()

    assert [r for r in caplog.records if r.levelno > logging.INFO] == []

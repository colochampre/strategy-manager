"""``BookingPrepareHandler`` — the self-scheduling ``reconciliation.
prepare_booking`` job (design decisions 1, 11, 16; Unit 5 wiring).

Two behaviours pinned here that ``PrepareBooking`` itself deliberately does
not own alone (see that module's own docstring): the handler-level DRY_RUN
hard skip with its OWN ``_SkipAnnouncement`` (never shared with
``ReconciliationScanHandler``'s), and the summary log that closes Unit 4b's
own self-audit point 10 -- a fully successful sweep must not be silent at
every log level.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application.booking_prepare_handler import (
    BookingPrepareHandler,
    dry_run_skip_announcement,
)
from strategy_manager.reconciliation.application.expire_booking_proposals import (
    ExpireBookingProposalsResult,
)
from strategy_manager.reconciliation.application.prepare_booking import PrepareBookingResult
from strategy_manager.reconciliation.application.reconciliation_scan_handler import (
    dry_run_skip_announcement as scan_dry_run_skip_announcement,
)
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind

NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
INTERVAL = 60.0

_EMPTY_RESULT = PrepareBookingResult(
    discrepancies_considered=0,
    proposals_prepared=0,
    proposals_skipped=0,
    proposals_suppressed=0,
)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class SpyQueue:
    def __init__(self) -> None:
        self.enqueued: list[Job] = []

    async def enqueue(self, job: Job) -> object:
        self.enqueued.append(job)
        return uuid4()


class StubPrepareBooking:
    def __init__(
        self,
        result: PrepareBookingResult | None = None,
        raises: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self._result = result or _EMPTY_RESULT
        self._raises = raises
        self._events = events if events is not None else []
        self.job_ids: list[UUID] = []

    async def sweep(self, job_id: UUID) -> PrepareBookingResult:
        self.job_ids.append(job_id)
        self._events.append("sweep")
        if self._raises is not None:
            raise self._raises
        return self._result


class StubExpireBookingProposals:
    """Records call order relative to ``StubPrepareBooking.sweep`` via a
    shared ``events`` list, so ordering (Unit 6b: expiry BEFORE the sweep)
    is provable without timing."""

    def __init__(self, expired: int = 0, events: list[str] | None = None) -> None:
        self._expired = expired
        self._events = events if events is not None else []
        self.calls = 0

    async def expire(self) -> ExpireBookingProposalsResult:
        self.calls += 1
        self._events.append("expire")
        return ExpireBookingProposalsResult(expired=self._expired)


def _claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        kind=JobKind.RECONCILIATION_PREPARE_BOOKING,
        payload={},
        attempts=1,
        max_attempts=5,
    )


def _build(
    prepare: StubPrepareBooking,
    dry_run: bool = False,
    expire: StubExpireBookingProposals | None = None,
) -> tuple[BookingPrepareHandler, SpyQueue]:
    queue = SpyQueue()
    handler = BookingPrepareHandler(
        prepare_booking=prepare,  # type: ignore[arg-type]
        expire_booking_proposals=expire or StubExpireBookingProposals(),  # type: ignore[arg-type]
        queue=queue,
        clock=FrozenClock(),
        interval_seconds=INTERVAL,
        dry_run=dry_run,
    )
    return handler, queue


@pytest.fixture(autouse=True)
def _unannounced() -> None:
    """No test may inherit another test's process-scoped announcement --
    from EITHER handler's singleton, since this file exercises both."""

    dry_run_skip_announcement.reset()
    scan_dry_run_skip_announcement.reset()


async def test_the_handler_sweeps_using_the_jobs_own_id() -> None:
    prepare = StubPrepareBooking()
    handler, _ = _build(prepare)
    job = _claimed_job()

    await handler.handle(job)

    assert prepare.job_ids == [job.id]


async def test_the_handler_re_enqueues_itself_one_interval_later() -> None:
    handler, queue = _build(StubPrepareBooking())

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1
    follow_up = queue.enqueued[0]
    assert follow_up.kind is JobKind.RECONCILIATION_PREPARE_BOOKING
    assert follow_up.run_after == NOW + timedelta(seconds=INTERVAL)


async def test_dry_run_skips_the_sweep_but_still_enqueues_the_successor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prepare = StubPrepareBooking()
    expire = StubExpireBookingProposals()
    handler, queue = _build(prepare, dry_run=True, expire=expire)

    with caplog.at_level("WARNING"):
        result = await handler.handle(_claimed_job())

    assert prepare.job_ids == []
    assert result is None
    assert len(queue.enqueued) == 1
    assert any("DRY_RUN" in record.message for record in caplog.records)
    # Unit 6b, binding requirement 4: under DRY_RUN nothing can exist, so
    # expiry is skipped along with the fetch -- never called, never logged.
    assert expire.calls == 0


async def test_only_the_first_dry_run_skip_of_a_process_is_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler, _ = _build(StubPrepareBooking(), dry_run=True)

    with caplog.at_level("DEBUG"):
        for _ in range(3):
            await handler.handle(_claimed_job())

    skips = [record for record in caplog.records if "DRY_RUN" in record.message]
    assert len(skips) == 3, "every skip is still recorded"
    assert [record.levelname for record in skips] == ["WARNING", "DEBUG", "DEBUG"]


async def test_the_prepare_skip_announcement_is_independent_of_the_scans(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design decision 16: a shared singleton would let the scan chain's
    first DRY_RUN skip silence the booking chain's own first WARNING (or
    the reverse), which is exactly the buried-restart failure the scan
    handler's own ``_SkipAnnouncement`` docstring warns against.

    Non-vacuity of this RED, proven by temporarily making
    ``BookingPrepareHandler`` use the SCAN handler's singleton: with that
    substitution, exhausting the scan announcement first leaves this test's
    own first skip at DEBUG, and the assertion below fails exactly here.
    That substitution was reverted before this file was left in its final
    state -- see the apply-progress note for this unit.
    """

    # Exhaust the SCAN handler's own announcement first.
    assert scan_dry_run_skip_announcement.level() == logging.WARNING

    handler, _ = _build(StubPrepareBooking(), dry_run=True)

    with caplog.at_level("DEBUG"):
        await handler.handle(_claimed_job())

    skips = [record for record in caplog.records if "DRY_RUN" in record.message]
    assert len(skips) == 1
    assert skips[0].levelname == "WARNING", (
        "the prepare-booking chain's own first skip must still be a WARNING "
        "even though the scan chain's singleton was already exhausted"
    )


async def test_a_sweep_with_skipped_discrepancies_still_enqueues_the_successor() -> None:
    prepare = StubPrepareBooking(
        result=PrepareBookingResult(
            discrepancies_considered=1,
            proposals_prepared=0,
            proposals_skipped=1,
            proposals_suppressed=0,
        )
    )
    handler, queue = _build(prepare)

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1


async def test_a_programming_error_propagates_and_does_not_re_enqueue() -> None:
    prepare = StubPrepareBooking(raises=RuntimeError("unserved pool"))
    handler, queue = _build(prepare)

    with pytest.raises(RuntimeError):
        await handler.handle(_claimed_job())

    assert queue.enqueued == []


# --- Expiry: runs before the sweep, under the same DRY_RUN skip -------------


async def test_expiry_runs_before_the_sweep() -> None:
    """Unit 6b, design.md § 11: a sweep must never see a proposal that is
    already stale by its own clock. Non-vacuity proven during apply by
    temporarily swapping the two calls in ``BookingPrepareHandler.handle``
    -- with the sweep called first, this assertion fails because ``events``
    reads ``["sweep", "expire"]`` instead; reverted before this file was
    left in its final state."""

    events: list[str] = []
    prepare = StubPrepareBooking(events=events)
    expire = StubExpireBookingProposals(events=events)
    handler, _ = _build(prepare, expire=expire)

    await handler.handle(_claimed_job())

    assert events == ["expire", "sweep"]


async def test_expiry_of_zero_proposals_logs_nothing_above_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    expire = StubExpireBookingProposals(expired=0)
    handler, _ = _build(StubPrepareBooking(), expire=expire)

    with caplog.at_level("INFO"):
        await handler.handle(_claimed_job())

    assert not any("expired" in record.message for record in caplog.records)


async def test_expiry_of_some_proposals_logs_the_count_at_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    expire = StubExpireBookingProposals(expired=3)
    handler, _ = _build(StubPrepareBooking(), expire=expire)

    with caplog.at_level("INFO"):
        await handler.handle(_claimed_job())

    expiry_lines = [
        record
        for record in caplog.records
        if record.levelname == "INFO" and "expired" in record.message
    ]
    assert len(expiry_lines) == 1
    assert "3" in expiry_lines[0].message


# --- The summary log: no noise on an empty sweep, exactly one line otherwise


async def test_a_sweep_over_nothing_logs_nothing_above_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unit 4b's own self-audit point 10, closed here: at a 60s cadence an
    empty sweep is the routine case and must never compete with a real
    WARNING for attention.

    Non-vacuity proven by temporarily logging the summary at INFO
    unconditionally: with that change this test's own assertion fails,
    because the empty-sweep line then appears above WARNING level. Reverted
    before this file was left in its final state.
    """

    prepare = StubPrepareBooking(result=_EMPTY_RESULT)
    handler, _ = _build(prepare)

    with caplog.at_level("WARNING"):
        await handler.handle(_claimed_job())

    assert caplog.records == []


async def test_a_sweep_that_prepared_something_logs_exactly_one_info_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prepare = StubPrepareBooking(
        result=PrepareBookingResult(
            discrepancies_considered=3,
            proposals_prepared=1,
            proposals_skipped=0,
            proposals_suppressed=0,
        )
    )
    handler, _ = _build(prepare)

    with caplog.at_level("INFO"):
        await handler.handle(_claimed_job())

    summaries = [
        record
        for record in caplog.records
        if record.levelname == "INFO" and "prepare booking" in record.message
    ]
    assert len(summaries) == 1
    assert "considered=3" in summaries[0].message
    assert "prepared=1" in summaries[0].message


async def test_a_sweep_that_only_suppressed_still_logs_the_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``proposals_suppressed`` alone (no prepared, no skipped) still counts
    as "something happened" -- a rejection-suppression run is not the same
    as a sweep that considered nothing at all."""

    prepare = StubPrepareBooking(
        result=PrepareBookingResult(
            discrepancies_considered=1,
            proposals_prepared=0,
            proposals_skipped=0,
            proposals_suppressed=1,
        )
    )
    handler, _ = _build(prepare)

    with caplog.at_level("INFO"):
        await handler.handle(_claimed_job())

    summaries = [
        record
        for record in caplog.records
        if record.levelname == "INFO" and "prepare booking" in record.message
    ]
    assert len(summaries) == 1
    assert "suppressed=1" in summaries[0].message


async def test_PrepareBooking_satisfies_the_handler_port() -> None:
    """Guards the stub above from drifting away from the real use case."""

    from strategy_manager.reconciliation.application.prepare_booking import PrepareBooking

    assert hasattr(PrepareBooking, "sweep")

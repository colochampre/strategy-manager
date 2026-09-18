"""``ReconciliationScanHandler`` — the self-scheduling ``reconciliation.scan``
job (design decisions 8, 11; Phase 5 wiring).

Two behaviours pinned here that ``ScanPools`` itself deliberately does not
own (see that module's own docstring): the DRY_RUN hard skip, and the
successor enqueue that happens whether the scan ran clean, skipped some
pools internally, or was hard-skipped for DRY_RUN -- unlike
``BalanceSyncHandler``/``SweepHandler``, which enqueue only after their use
case returns without raising.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application.reconciliation_scan_handler import (
    ReconciliationScanHandler,
)
from strategy_manager.reconciliation.application.scan_pools import ScanPools, ScanResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
INTERVAL = 30.0

_CLEAN_RESULT = ScanResult(
    pools_scanned=1, pools_skipped=0, discrepancies_opened=0, discrepancies_resolved=0
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


class StubScanPools:
    def __init__(
        self, result: ScanResult | None = None, raises: Exception | None = None
    ) -> None:
        self._result = result or _CLEAN_RESULT
        self._raises = raises
        self.scan_ids: list[UUID] = []

    async def scan(self, scan_id: UUID) -> ScanResult:
        self.scan_ids.append(scan_id)
        if self._raises is not None:
            raise self._raises
        return self._result


def _claimed_job() -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(), kind=JobKind.RECONCILIATION_SCAN, payload={}, attempts=1, max_attempts=5
    )


def _build(
    scan: StubScanPools, dry_run: bool = False
) -> tuple[ReconciliationScanHandler, SpyQueue]:
    queue = SpyQueue()
    handler = ReconciliationScanHandler(
        scan_pools=scan,  # type: ignore[arg-type]
        queue=queue,
        clock=FrozenClock(),
        interval_seconds=INTERVAL,
        dry_run=dry_run,
    )
    return handler, queue


async def test_the_handler_scans_using_the_jobs_own_id_as_scan_id() -> None:
    scan = StubScanPools()
    handler, _ = _build(scan)
    job = _claimed_job()

    await handler.handle(job)

    assert scan.scan_ids == [job.id]


async def test_the_handler_re_enqueues_itself_one_interval_later() -> None:
    handler, queue = _build(StubScanPools())

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1
    follow_up = queue.enqueued[0]
    assert follow_up.kind is JobKind.RECONCILIATION_SCAN
    assert follow_up.run_after == NOW + timedelta(seconds=INTERVAL)


async def test_dry_run_skips_the_scan_but_still_enqueues_the_successor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Design decision 11 verbatim: DRY_RUN is a hard skip INSIDE the
    handler, logged at WARNING -- skipping the seeding instead would make
    the skip silent."""

    scan = StubScanPools()
    handler, queue = _build(scan, dry_run=True)

    with caplog.at_level("WARNING"):
        result = await handler.handle(_claimed_job())

    assert scan.scan_ids == []
    assert result is None
    assert len(queue.enqueued) == 1
    assert any("DRY_RUN" in record.message for record in caplog.records)


async def test_a_scan_with_skipped_pools_still_enqueues_the_successor() -> None:
    """Design decision 8: a per-pool venue read failure is already swallowed
    inside ``ScanPools`` and returns normally with ``pools_skipped`` set, so
    the successor must not be withheld for it -- deliberately unlike
    ``BalanceSyncHandler``, which enqueues only on success."""

    scan = StubScanPools(
        result=ScanResult(
            pools_scanned=1, pools_skipped=1, discrepancies_opened=0, discrepancies_resolved=0
        )
    )
    handler, queue = _build(scan)

    await handler.handle(_claimed_job())

    assert len(queue.enqueued) == 1


async def test_a_programming_error_propagates_and_does_not_re_enqueue() -> None:
    """Unlike a per-pool venue error (already swallowed inside ``ScanPools``),
    anything else is a programming error and must stay loud: a worker
    restart re-seeds the chain, which is the documented recovery."""

    scan = StubScanPools(raises=RuntimeError("unserved pool"))
    handler, queue = _build(scan)

    with pytest.raises(RuntimeError):
        await handler.handle(_claimed_job())

    assert queue.enqueued == []


async def test_ScanPools_satisfies_the_handler_port() -> None:
    """Guards the stub above from drifting away from the real use case."""

    assert hasattr(ScanPools, "scan")

"""``BookingPrepareHandler``: the ``reconciliation.prepare_booking`` job
handler wrapping ``PrepareBooking`` (design decisions 1, 11, 16;
``prepare_booking.py``'s own docstring names this class as the one that
owns Unit 5's handler-level DRY_RUN skip).

Self-scheduling, mirroring ``ReconciliationScanHandler`` exactly: no cron, no
external scheduler, each run enqueues its own successor. It owns the two
behaviours ``PrepareBooking`` deliberately does NOT own alone: the
handler-level DRY_RUN hard skip, and deciding when the successor is
enqueued.

**Why this handler carries its OWN ``_SkipAnnouncement`` (design decision
16).** ``ReconciliationScanHandler`` already has one, process-scoped, module
-level. Sharing that singleton here would make the two chains cannibalise
each other's one loud WARNING: if the scan handler's job happened to run
first in a DRY_RUN process, this handler's own first skip would already be
silenced to DEBUG, and a operator restarting the worker specifically to see
why booking never prepares anything would find nothing at WARNING. Each
chain announces its own configuration state once, independently.

**Why the handler skips BEFORE calling ``sweep`` at all, even though
``PrepareBooking`` already refuses internally under ``dry_run=True``
(``prepare_booking.py``'s flagged deviation).** That constructor argument
exists so the DRY_RUN refusal is provable at the use-case level with fakes
only (design decision 16's own test name,
``test_dry_run_hard_skip_no_fetch_no_proposal``) -- defense in depth, not a
replacement for this handler's own hard skip. Building a real
``VenueFillReaderRegistry`` still costs nothing extra here because
``main.py`` builds venue fill readers only when ``settings.dry_run`` is
``False``, mirroring ``handle_reconciliation_scan``'s identical guard around
its own venue position readers -- so under DRY_RUN, ``PrepareBooking`` is
constructed with an EMPTY registry and this handler never calls ``sweep`` on
it regardless.

**The successor enqueue (mirrors design decision 8 for the scan handler).**
Reached after every outcome that returns normally: a clean sweep, a sweep
that skipped or suppressed some discrepancies internally (``PrepareBooking``
already returns normally in that case), and the DRY_RUN hard skip above. A
genuine programming error -- an unserved pool, a bug -- is NOT swallowed
anywhere in this pipeline and propagates out of ``sweep()`` before the
enqueue call below is ever reached, so no successor is written for it; a
worker restart re-seeds the chain (``RecurringJobSeeder``), the same
documented recovery every other chain here relies on.

**The summary log (Unit 4b's own self-audit, point 10).** A successful
``PrepareBooking.sweep`` logs nothing per-discrepancy for the one path that
matched, inserted, and was counted prepared -- deliberately, so a healthy
proposal does not compete with the WARNINGs that mean something went wrong.
Left unaddressed, a fully successful sweep would produce ZERO log output at
any level, which is exactly the silent-failure shape this whole change
exists to close for ``balance.sync``. So this handler logs ONE INFO summary
line whenever anything besides ``discrepancies_considered`` moved, and
nothing above DEBUG for a sweep over nothing -- the routine, expected case
at a 60-second cadence.
"""

import logging
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from strategy_manager.reconciliation.application.prepare_booking import PrepareBookingResult
from strategy_manager.shared.application.job import ClaimedJob, Job, JobKind
from strategy_manager.shared.application.ports import ClockPort, JobQueuePort

logger = logging.getLogger(__name__)


class _SkipAnnouncement:
    """Announces the DRY_RUN skip loudly once per worker PROCESS.

    A deliberate near-duplicate of
    ``reconciliation_scan_handler._SkipAnnouncement`` rather than a shared
    import of it -- see this module's own docstring for why the two chains
    must never share one singleton. Process-scoped for the identical reason
    that class states: ``main.py`` constructs a fresh handler for every
    claimed job, so instance state would reset every interval and announce
    nothing.
    """

    def __init__(self) -> None:
        self._announced = False

    def level(self) -> int:
        if self._announced:
            return logging.DEBUG
        self._announced = True
        return logging.WARNING

    def reset(self) -> None:
        """For tests, which must not inherit another test's announcement."""

        self._announced = False


dry_run_skip_announcement = _SkipAnnouncement()


class PrepareBookingPort(Protocol):
    """What the handler needs from ``PrepareBooking``, declared here so the
    handler never depends on the use case's construction."""

    async def sweep(self, job_id: UUID) -> PrepareBookingResult: ...


def _log_summary(result: PrepareBookingResult) -> None:
    if (
        result.proposals_prepared
        or result.proposals_skipped
        or result.proposals_suppressed
    ):
        logger.info(
            "prepare booking: considered=%d prepared=%d skipped=%d suppressed=%d",
            result.discrepancies_considered,
            result.proposals_prepared,
            result.proposals_skipped,
            result.proposals_suppressed,
        )
        return
    # Nothing happened -- the routine case at this cadence. Still visible at
    # DEBUG for anyone who goes looking, never silent, never louder than
    # that: an empty sweep every 60s at INFO would be the exact "everything
    # is fine" noise this change's own watchdog docstring warns trains a
    # reader to stop reading.
    logger.debug(
        "prepare booking: considered=%d, nothing else happened",
        result.discrepancies_considered,
    )


class BookingPrepareHandler:
    def __init__(
        self,
        prepare_booking: PrepareBookingPort,
        queue: JobQueuePort,
        clock: ClockPort,
        interval_seconds: float,
        dry_run: bool,
    ) -> None:
        self._prepare_booking = prepare_booking
        self._queue = queue
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._dry_run = dry_run

    async def handle(self, job: ClaimedJob) -> PrepareBookingResult | None:
        if self._dry_run:
            logger.log(
                dry_run_skip_announcement.level(),
                "prepare booking skipped for job %s: DRY_RUN is enabled; no "
                "venue fetch, no proposal",
                job.id,
            )
            result = None
        else:
            # The claimed job's own id, never a freshly minted one --
            # ``PrepareBooking.sweep`` lands it verbatim as
            # ``prepared_by_job_id`` on every proposal frozen this sweep,
            # the same convention ``ScanPools.scan`` already follows for
            # ``first_scan_id``/``last_scan_id``.
            result = await self._prepare_booking.sweep(job.id)
            _log_summary(result)

        await self._queue.enqueue(
            Job(
                kind=JobKind.RECONCILIATION_PREPARE_BOOKING,
                run_after=self._clock.now() + timedelta(seconds=self._interval_seconds),
            )
        )
        return result

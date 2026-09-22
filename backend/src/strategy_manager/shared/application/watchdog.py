"""``Watchdog``: the periodic check for SILENCE.

The ERROR bridge (``alert_log_bridge.py``) forwards what this system SAYS.
This exists for what it stops saying. ``balance.sync`` was dead in production
from 2026-09-18 to 2026-09-21 — three days. It logged WARNINGs on every retry,
then the chain exhausted ``max_attempts``, went FAILED, and logged nothing at
all. The deployment looked alive the entire time. Nothing that only reacts to
an error can ever catch that, because the defining feature of the outage is the
absence of output.

So this asks, on a cadence, four questions whose answers a dead component
cannot suppress:

1. Is any enabled pool's newest balance snapshot older than the bound? That is
   ``balance.sync`` not writing, whatever the reason.
2. Does any recurring chain have nothing PENDING or CLAIMED? That is the
   three-day failure exactly — a chain that ended with nothing scheduled.
3. Did anything end FAILED since the previous run? A FAILED row is the only
   trace a dead chain leaves, and ``jobs.purge`` deliberately never deletes one.
4. Has the alert channel dropped anything? A lossy channel means silence no
   longer implies health, which invalidates every other answer here.

**It reads the DATABASE ONLY.** Never a venue. A watchdog that can be made to
hang by an exchange's socket is a watchdog that stops watching exactly when
things are going wrong, and its own failure would then kill its chain.

**It reports by LOGGING ERROR, never by calling the alerter.** Unit 1's bridge
does the delivery, so there is exactly one alerting path, one throttle and one
redaction pass. Calling an ``AlertPort`` from here would be a second path with
none of that.

**One ERROR per condition, not per finding and not one combined message.** The
bridge throttles on (logger, message template): four conditions sharing one
template would put four independent incidents behind one 15-minute key, and a
template per stale POOL would let the first pool suppress the second. So each
condition logs once, naming everything it found.

**A healthy run is silent** — one INFO line and nothing louder. This runs every
few minutes for the life of the deployment. A watchdog that chirps on every run
trains its reader to skip it, which is the original defect with an extra step.

THE HOLE, stated rather than papered over: this is itself a recurring chain, so
it cannot report its own death. If the watchdog's job dies, or the worker
process stops claiming at all, every check above stops running and the silence
is once again indistinguishable from health. ``RecurringChainRevival`` re-seeds
a dead chain from inside the claim loop, which covers the first case as long as
the loop is alive, and nothing in this process can cover the second. The only
real answer is external: a dead-man's switch outside this deployment that
expects a periodic ping and alerts when it stops arriving. Do not try to solve
it in here — anything that watches this process from inside it dies with it.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StalePool:
    """One enabled pool whose balance snapshot is too old, or absent.

    ``age_seconds`` is ``None`` when no snapshot has EVER been written for the
    pool. That is a different incident from a lapsed sync — a misconfiguration
    rather than a failure — and flattening it to a very large age would hide
    which one the operator is looking at.
    """

    exchange: str
    venue: str
    settlement_currency: str
    age_seconds: float | None

    @property
    def key(self) -> str:
        return f"{self.exchange}/{self.venue}/{self.settlement_currency}"

    def describe(self) -> str:
        if self.age_seconds is None:
            return f"{self.key} (never synced)"
        return f"{self.key} ({self.age_seconds:.0f}s old)"


@dataclass(frozen=True, slots=True)
class FailedJobs:
    """How many jobs of one kind ended FAILED inside the window.

    ``kind`` is a plain string, not a ``JobKind``: the table can hold a kind
    this build no longer knows about (an older deployment's, a renamed one),
    and a watchdog that raised on an unrecognised row would fail to report the
    very outage it was reading about.
    """

    kind: str
    count: int


class StaleSnapshotPort(Protocol):
    """Enabled pools whose newest balance snapshot is older than the bound.

    Must include a pool with NO snapshot row at all — that pool is the most
    broken one, and an inner join answers for it with silence.
    """

    async def stale_pools(self, max_age_seconds: float) -> Sequence[StalePool]: ...


class JobHealthPort(Protocol):
    """The two questions this asks of the ``jobs`` table.

    One port rather than two because they are one adapter over one table, and
    every fake that stands in for it would otherwise have to be written twice.
    """

    async def kinds_without_live_job(
        self, kinds: Sequence[JobKind]
    ) -> Sequence[JobKind]:
        """The kinds with no PENDING and no CLAIMED row, in the order asked."""
        ...

    async def failures_since(self, since: datetime) -> Sequence[FailedJobs]:
        """FAILED jobs per kind, from ``since`` inclusive."""
        ...


class AlertChannelPort(Protocol):
    """Whatever carries the alerts, asked only how much it has thrown away.

    ``AlertLogBridge`` satisfies this structurally. Deliberately read-only and
    one field wide: the watchdog must never be able to SEND through the alert
    path, only to notice that the path is lossy.
    """

    @property
    def dropped(self) -> int: ...


@dataclass(frozen=True, slots=True)
class WatchdogReport:
    """What one run found. Returned for the handler and the tests; the ERRORs
    are the real output, and nothing branches on this."""

    checked_at: datetime
    stale_pools: tuple[StalePool, ...]
    unscheduled_kinds: tuple[JobKind, ...]
    failures: tuple[FailedJobs, ...]
    dropped_alerts: int

    @property
    def healthy(self) -> bool:
        return not (
            self.stale_pools
            or self.unscheduled_kinds
            or self.failures
            or self.dropped_alerts
        )


class Watchdog:
    def __init__(
        self,
        *,
        jobs: JobHealthPort,
        snapshots: StaleSnapshotPort,
        alert_channel: AlertChannelPort | None,
        clock: ClockPort,
        recurring_kinds: Sequence[JobKind],
        snapshot_max_age_seconds: float,
        lookback_seconds: float,
    ) -> None:
        self._jobs = jobs
        self._snapshots = snapshots
        self._alert_channel = alert_channel
        self._clock = clock
        self._recurring_kinds = tuple(recurring_kinds)
        self._snapshot_max_age_seconds = snapshot_max_age_seconds
        self._lookback_seconds = lookback_seconds

    async def check(self, since: datetime | None = None) -> WatchdogReport:
        """One pass. ``since`` is the previous run's ``checked_at``; ``None``
        means nobody knows, so one interval of history is re-read rather than
        the whole table — a FAILED row is never purged, and re-reporting every
        failure this deployment has ever had is its own kind of silence."""
        now = self._clock.now()
        window_start = since or now - timedelta(seconds=self._lookback_seconds)

        report = WatchdogReport(
            checked_at=now,
            stale_pools=tuple(
                await self._snapshots.stale_pools(self._snapshot_max_age_seconds)
            ),
            unscheduled_kinds=tuple(
                await self._jobs.kinds_without_live_job(self._recurring_kinds)
            ),
            failures=tuple(await self._jobs.failures_since(window_start)),
            dropped_alerts=(
                self._alert_channel.dropped if self._alert_channel is not None else 0
            ),
        )
        self._report(report, window_start)
        return report

    def _report(self, report: WatchdogReport, window_start: datetime) -> None:
        if report.healthy:
            # The whole healthy run, in one line. It is an INFO rather than
            # nothing so that the journal still shows the watchdog running —
            # but it is never a WARNING, because "everything is fine" reaching
            # an operator's phone is how the phone stops being read.
            logger.info(
                "watchdog: every enabled pool has a fresh balance snapshot, every "
                "recurring chain has a job scheduled, and nothing has failed since %s",
                window_start.isoformat(),
            )
            return

        if report.stale_pools:
            logger.error(
                "watchdog: %d enabled pool(s) have no balance snapshot newer than "
                "%.0fs: %s. balance.sync is not refreshing them, so allocation is "
                "sizing against a balance that may no longer be true — or refusing "
                "to size at all.",
                len(report.stale_pools),
                self._snapshot_max_age_seconds,
                ", ".join(pool.describe() for pool in report.stale_pools),
            )

        if report.unscheduled_kinds:
            logger.error(
                "watchdog: recurring chain(s) with nothing scheduled: %s. Each one "
                "has no PENDING and no CLAIMED job, so it has stopped running "
                "entirely and will not restart on its own.",
                ", ".join(kind.value for kind in report.unscheduled_kinds),
            )

        if report.failures:
            logger.error(
                "watchdog: job(s) ended FAILED since %s: %s. A FAILED job spent "
                "every retry it had; a recurring one took its chain down with it.",
                window_start.isoformat(),
                ", ".join(
                    f"{failed.kind} x{failed.count}" for failed in report.failures
                ),
            )

        if report.dropped_alerts:
            # Cumulative for the life of the process, so this keeps firing
            # once it has fired — correctly. A channel that lost an alert is
            # still a channel whose silence proves nothing, and the throttle
            # keeps it to one message per window either way.
            logger.error(
                "watchdog: the alert channel has dropped %d alert(s) since this "
                "process started. Alerts are being thrown away, so a quiet channel "
                "no longer means a healthy system.",
                report.dropped_alerts,
            )

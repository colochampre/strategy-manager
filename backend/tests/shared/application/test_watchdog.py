"""``Watchdog`` — the periodic check for SILENCE.

The ERROR bridge (unit 1) forwards what the system says. This exists for what
it stops saying: ``balance.sync`` was dead in production from 2026-09-18 to
2026-09-21, warning on every retry and then saying nothing at all, while the
deployment looked alive. Nothing that only reacts to an ERROR can catch that.

Two properties are pinned hardest here, and they pull in opposite directions.
Every unhealthy condition must produce its OWN ERROR record, because the alert
bridge throttles by (logger, message template) and one giant message would put
four independent incidents behind a single 15-minute key. And a healthy run
must be SILENT — at most one INFO — because a watchdog that chirps every five
minutes is a watchdog whose owner learns to ignore it, which is the original
defect with an extra step.

No database: the use case reads through ports, and the real SQL is pinned by
the integration tests beside each adapter.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.application.watchdog import (
    FailedJobs,
    StalePool,
    Watchdog,
)

NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)
WATCHDOG_LOGGER = "strategy_manager.shared.application.watchdog"
SNAPSHOT_MAX_AGE = 600.0
LOOKBACK = 300.0

RECURRING = (JobKind.RESERVATION_SWEEP, JobKind.BALANCE_SYNC, JobKind.JOBS_PURGE)

BYBIT_POOL = StalePool(
    exchange="bybit", venue="usdt-m", settlement_currency="USDT", age_seconds=4_212.0
)
NEVER_SYNCED_POOL = StalePool(
    exchange="binance", venue="usdt-m", settlement_currency="USDT", age_seconds=None
)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeJobHealth:
    def __init__(
        self,
        unscheduled: tuple[JobKind, ...] = (),
        failures: tuple[FailedJobs, ...] = (),
    ) -> None:
        self._unscheduled = unscheduled
        self._failures = failures
        self.asked_about: list[JobKind] = []
        self.asked_since: datetime | None = None

    async def kinds_without_live_job(
        self, kinds: tuple[JobKind, ...]
    ) -> list[JobKind]:
        self.asked_about = list(kinds)
        return list(self._unscheduled)

    async def failures_since(self, since: datetime) -> list[FailedJobs]:
        self.asked_since = since
        return list(self._failures)


class FakeStaleSnapshots:
    def __init__(self, stale: tuple[StalePool, ...] = ()) -> None:
        self._stale = stale
        self.asked_max_age: float | None = None

    async def stale_pools(self, max_age_seconds: float) -> list[StalePool]:
        self.asked_max_age = max_age_seconds
        return list(self._stale)


class FakeAlertChannel:
    def __init__(self, dropped: int) -> None:
        self._dropped = dropped

    @property
    def dropped(self) -> int:
        return self._dropped


def _watchdog(
    *,
    jobs: FakeJobHealth | None = None,
    snapshots: FakeStaleSnapshots | None = None,
    alert_channel: FakeAlertChannel | None = None,
) -> Watchdog:
    return Watchdog(
        jobs=jobs or FakeJobHealth(),
        snapshots=snapshots or FakeStaleSnapshots(),
        alert_channel=alert_channel,
        clock=FrozenClock(),
        recurring_kinds=RECURRING,
        snapshot_max_age_seconds=SNAPSHOT_MAX_AGE,
        lookback_seconds=LOOKBACK,
    )


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == logging.ERROR]


# --- 1: a stale balance snapshot -----------------------------------------


async def test_a_stale_pool_is_an_error_naming_the_pool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    watchdog = _watchdog(snapshots=FakeStaleSnapshots((BYBIT_POOL,)))

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.stale_pools == (BYBIT_POOL,)
    errors = _errors(caplog)
    assert len(errors) == 1
    assert "bybit/usdt-m/USDT" in errors[0].getMessage()


async def test_a_pool_that_has_never_synced_is_reported_as_such(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``None`` is not ``0`` seconds old. A pool nothing has ever written a
    snapshot for is a misconfiguration, not a lapsed sync, and the message has
    to be able to tell the operator which one they are looking at."""
    watchdog = _watchdog(snapshots=FakeStaleSnapshots((NEVER_SYNCED_POOL,)))

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        await watchdog.check()

    message = _errors(caplog)[0].getMessage()
    assert "binance/usdt-m/USDT" in message
    assert "never synced" in message


async def test_the_configured_staleness_bound_is_the_one_asked_for() -> None:
    snapshots = FakeStaleSnapshots()
    await _watchdog(snapshots=snapshots).check()

    assert snapshots.asked_max_age == SNAPSHOT_MAX_AGE


# --- 2: a recurring chain with nothing scheduled --------------------------


async def test_a_chain_with_nothing_scheduled_is_an_error_naming_the_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The three-day failure, exactly: no PENDING and no CLAIMED job for a
    chain that is supposed to enqueue its own successor forever."""
    watchdog = _watchdog(jobs=FakeJobHealth(unscheduled=(JobKind.BALANCE_SYNC,)))

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.unscheduled_kinds == (JobKind.BALANCE_SYNC,)
    errors = _errors(caplog)
    assert len(errors) == 1
    assert JobKind.BALANCE_SYNC.value in errors[0].getMessage()


async def test_every_configured_recurring_kind_is_asked_about() -> None:
    jobs = FakeJobHealth()
    await _watchdog(jobs=jobs).check()

    assert jobs.asked_about == list(RECURRING)


# --- 3: jobs that ended FAILED since the previous run ---------------------


async def test_failed_jobs_are_reported_per_kind_with_the_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failures = (
        FailedJobs(kind=JobKind.BALANCE_SYNC.value, count=3),
        FailedJobs(kind=JobKind.SIGNAL_PROCESS.value, count=1),
    )
    watchdog = _watchdog(jobs=FakeJobHealth(failures=failures))

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.failures == failures
    message = _errors(caplog)[0].getMessage()
    assert "balance.sync" in message
    assert "3" in message
    assert "signal.process" in message


async def test_the_failure_window_starts_at_the_previous_run() -> None:
    """A FAILED row is never purged, so without a window every run would
    re-report every failure this deployment has ever had."""
    jobs = FakeJobHealth()
    previous = NOW - timedelta(seconds=42)

    await _watchdog(jobs=jobs).check(previous)

    assert jobs.asked_since == previous


async def test_an_unknown_previous_run_falls_back_to_one_interval() -> None:
    jobs = FakeJobHealth()

    await _watchdog(jobs=jobs).check(None)

    assert jobs.asked_since == NOW - timedelta(seconds=LOOKBACK)


# --- 4: a lossy alert channel ---------------------------------------------


async def test_a_lossy_alert_channel_is_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A dropped alert is the one failure the alert path cannot report about
    itself: whatever it was carrying never arrived."""
    watchdog = _watchdog(alert_channel=FakeAlertChannel(dropped=7))

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.dropped_alerts == 7
    errors = _errors(caplog)
    assert len(errors) == 1
    assert "7" in errors[0].getMessage()


async def test_a_channel_that_has_dropped_nothing_says_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    watchdog = _watchdog(alert_channel=FakeAlertChannel(dropped=0))

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.dropped_alerts == 0
    assert _errors(caplog) == []


async def test_alerting_being_off_is_not_a_condition(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The check runs whether or not alerting is enabled. With no channel
    there is nothing to be lossy, and a deployment that chose silence must not
    be told it is broken for having chosen it."""
    watchdog = _watchdog(alert_channel=None)

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.dropped_alerts == 0
    assert _errors(caplog) == []


# --- the shape of the reporting itself ------------------------------------


async def test_each_condition_gets_its_own_error_with_its_own_template(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The throttle key is (logger, message TEMPLATE). Four conditions in one
    message would share one key, so the second incident inside the window
    would be suppressed by the first — and they are independent failures."""
    watchdog = _watchdog(
        jobs=FakeJobHealth(
            unscheduled=(JobKind.BALANCE_SYNC,),
            failures=(FailedJobs(kind=JobKind.JOBS_PURGE.value, count=2),),
        ),
        snapshots=FakeStaleSnapshots((BYBIT_POOL,)),
        alert_channel=FakeAlertChannel(dropped=1),
    )

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        await watchdog.check()

    errors = _errors(caplog)
    assert len(errors) == 4
    assert len({record.msg for record in errors}) == 4


async def test_all_the_stale_pools_share_one_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One ERROR per CONDITION, not per pool. Two pools logged through the
    same template would be one throttle key, and the second pool would be
    suppressed for 15 minutes by the first."""
    watchdog = _watchdog(
        snapshots=FakeStaleSnapshots((BYBIT_POOL, NEVER_SYNCED_POOL))
    )

    with caplog.at_level(logging.INFO, logger=WATCHDOG_LOGGER):
        await watchdog.check()

    errors = _errors(caplog)
    assert len(errors) == 1
    assert "bybit/usdt-m/USDT" in errors[0].getMessage()
    assert "binance/usdt-m/USDT" in errors[0].getMessage()


async def test_a_healthy_run_logs_at_most_one_info_and_nothing_louder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The load-bearing test of this module. This runs every few minutes for
    the life of the deployment; a run that says anything notable when nothing
    is wrong trains its reader to skip the one that matters."""
    watchdog = _watchdog(alert_channel=FakeAlertChannel(dropped=0))

    with caplog.at_level(logging.DEBUG, logger=WATCHDOG_LOGGER):
        report = await watchdog.check()

    assert report.healthy is True
    assert [record for record in caplog.records if record.levelno > logging.INFO] == []
    assert len([r for r in caplog.records if r.levelno == logging.INFO]) <= 1


async def test_an_unhealthy_run_is_not_reported_as_healthy() -> None:
    watchdog = _watchdog(jobs=FakeJobHealth(unscheduled=(JobKind.JOBS_PURGE,)))

    report = await watchdog.check()

    assert report.healthy is False
    assert report.checked_at == NOW

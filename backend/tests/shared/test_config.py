"""Defaults for the settings whose number is itself a decision.

``RECONCILIATION_SCAN_INTERVAL_SECONDS`` is not a guess: Phase 0 measured it
live against both venues (scripts/measure_reconciliation_rate_limits.py) and
found the binding constraint is staleness/false-confirmation tolerance, not
either venue's rate limit — see ``config.py`` for the full arithmetic.

``RESERVATION_SWEEP_INTERVAL_SECONDS`` is pinned here because it used to be
``WORKER_POLL_INTERVAL_SECONDS`` reused as a scheduling interval, and that one
substitution wrote ~43,200 job rows a day for bookkeeping nothing waits on.
"""

from strategy_manager.shared.config import Settings


def test_reconciliation_scan_interval_defaults_to_thirty_seconds() -> None:
    assert Settings().reconciliation_scan_interval_seconds == 30.0


def test_reconciliation_confirmations_defaults_to_two() -> None:
    assert Settings().reconciliation_confirmations == 2


def test_reservation_sweep_interval_defaults_to_sixty_seconds() -> None:
    """Deliberately NOT the worker poll interval. Nothing reads the sweep for
    correctness — ``sum_active`` already excludes expired reservations — so its
    cadence is a bookkeeping choice, and a 2s one costs 43,200 rows a day."""

    assert Settings().reservation_sweep_interval_seconds == 60.0


def test_the_sweep_interval_is_not_tied_to_the_worker_poll_interval() -> None:
    """The bug this setting exists to prevent: one value doing double duty as
    both the worker's polling cadence and the sweeper's scheduling cadence."""

    settings = Settings()

    assert settings.reservation_sweep_interval_seconds != settings.worker_poll_interval_seconds


def test_job_retention_defaults_to_seven_days() -> None:
    """Long enough to investigate a weekend's worth of worker history, short
    enough that the table stays small."""

    assert Settings().job_retention_days == 7


def test_the_jobs_purge_runs_once_a_day() -> None:
    """Retention is measured in days, so a cadence finer than a day only
    scans the table more often to find the same rows."""

    assert Settings().jobs_purge_interval_seconds == 86_400.0

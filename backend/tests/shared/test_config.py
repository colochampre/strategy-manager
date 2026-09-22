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


def test_the_retry_backoff_absorbs_a_quarter_hour_of_transient_fault() -> None:
    """The number that matters is not either setting on its own, it is the
    window the two of them buy before a self-scheduling chain dies.

    With ``max_attempts=5`` the four waits between the five attempts are
    30 + 60 + 120 + 240 = 450s, and the fifth failure ends the job. Retrying
    with no delay at all spent 27 seconds of that window on 2026-09-18 and
    killed the balance.sync chain."""

    settings = Settings()
    base = settings.job_retry_backoff_base_seconds
    cap = settings.job_retry_backoff_max_seconds

    waits = [min(base * 2**attempt, cap) for attempt in range(4)]

    assert waits == [30.0, 60.0, 120.0, 240.0]
    assert sum(waits) == 450.0


def test_the_backoff_cap_is_not_reached_before_the_attempts_run_out() -> None:
    """A cap below the last wait would flatten the tail of the curve and cut
    the absorbed window short; 600s sits just above the 480s a sixth attempt
    would wait, so it bounds a longer chain without shortening this one."""

    settings = Settings()

    assert settings.job_retry_backoff_max_seconds == 600.0
    assert settings.job_retry_backoff_base_seconds * 2**3 < 600.0


def test_the_recurring_seed_interval_is_coarser_than_the_worker_poll() -> None:
    """Re-seeding takes an advisory lock and scans the jobs table. The claim
    loop ticks every 2s; a dead chain is an hours-scale event, so 5 minutes is
    the cadence, not the poll."""

    settings = Settings()

    assert settings.recurring_seed_interval_seconds == 300.0
    assert settings.recurring_seed_interval_seconds > settings.worker_poll_interval_seconds


def test_balance_sync_interval_defaults_to_sixty_seconds() -> None:
    """Raised from 15s (design.md § S3): a dead periodic sync no longer needs
    to be caught this fast now that ``RefreshPoolBalance`` refreshes on demand
    before an opening signal is sized. It must still stay under
    ``balance_snapshot_max_age_seconds`` so a snapshot can still be found
    FALLBACK-eligible rather than immediately UNAVAILABLE."""

    assert Settings().balance_sync_interval_seconds == 60.0


def test_balance_sync_interval_stays_under_the_snapshot_max_age() -> None:
    settings = Settings()

    assert settings.balance_sync_interval_seconds < settings.balance_snapshot_max_age_seconds


def test_balance_refresh_timeout_defaults_to_three_seconds() -> None:
    """Shorter than the venue client's own timeout, so a hung refresh gives up
    while there is still time for the fallback path to run before the signal
    itself is retried (design.md § S3)."""

    assert Settings().balance_refresh_timeout_seconds == 3.0


def test_venue_net_position_timeout_defaults_to_three_seconds() -> None:
    """The Existing-Position Guard's divergent-branch venue read (design.md
    § S4) -- the last remote call before the pool's advisory lock, exactly
    like the balance refresh above."""

    assert Settings().venue_net_position_timeout_seconds == 3.0


def test_open_after_close_settle_timeout_defaults_to_five_minutes() -> None:
    """design.md § S5: how long the continuation waits, from an awaited
    close's ``created_at``, before abandoning with an ERROR instead of
    polling forever for a close that never settles."""

    assert Settings().open_after_close_settle_timeout_seconds == 300.0


def test_open_after_close_poll_interval_defaults_to_five_seconds() -> None:
    """design.md § S5: the cadence of the continuation's own re-poll, once a
    fill usually lands in ~2s -- deliberately NOT the failure backoff
    (30/60/120/240/480s), which would hold a signal hostage for 30s after a
    fill that already landed."""

    assert Settings().open_after_close_poll_interval_seconds == 5.0


def test_alerts_are_disabled_until_they_are_turned_on() -> None:
    """The bridge is not installed at all when this is false, so an existing
    deployment that sets nothing keeps behaving exactly as it did — and a
    half-configured one cannot start sending to an empty chat id."""

    assert Settings(_env_file=None).alerts_enabled is False


def test_the_alert_channel_has_no_credential_by_default() -> None:
    """A default token would be a published credential, and a default chat id
    would be somebody else's phone."""

    settings = Settings(_env_file=None)

    assert settings.telegram_bot_token == ""
    assert settings.telegram_chat_id == ""


def test_the_alert_send_timeout_is_a_few_seconds() -> None:
    """The drain task sends one alert at a time, so this bounds how long a
    hung socket can hold every later ERROR behind it. Shorter than the venue
    clients' 10s: nothing downstream waits on an alert, so there is no reason
    to be patient with one."""

    assert Settings(_env_file=None).alert_send_timeout_seconds == 5.0


def test_the_alert_throttle_window_defaults_to_fifteen_minutes() -> None:
    """Long enough that a job exhausting its five attempts (450s of backoff)
    produces ONE alert rather than five, short enough that a chain still
    failing an hour later says so again."""

    assert Settings(_env_file=None).alert_throttle_window_seconds == 900.0


def test_the_throttle_window_outlives_a_whole_retry_chain() -> None:
    """The number this setting exists for: 30 + 60 + 120 + 240 = 450s of
    backoff between the five attempts. A window shorter than that alerts once
    per attempt, which is the flood the throttle is for."""

    settings = Settings()
    base = settings.job_retry_backoff_base_seconds
    cap = settings.job_retry_backoff_max_seconds
    waits = sum(min(base * 2**attempt, cap) for attempt in range(4))

    assert settings.alert_throttle_window_seconds > waits

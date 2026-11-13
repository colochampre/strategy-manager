"""``protective_stop.watch`` is only a recurring chain if something seeds it, watches it and
runs it (subscriber-safety SS.7; mirrors ``test_booking_prepare_wiring.py``'s structural
style).

A kind with no registered handler is FAILed by ``WorkerRunner`` on every claim and spends its
five attempts, and a stop watcher that never runs looks identical to a venue where no stop
ever fired: the fired stop would surface as a reconciliation discrepancy instead.
"""

import inspect

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.config import Settings
from strategy_manager.shared.infrastructure.recurring_jobs import RECURRING_KINDS


def test_the_kind_is_one_of_the_seeded_recurring_chains() -> None:
    """Seeded at startup like the others, revived by ``RecurringChainRevival`` if it ever
    exhausts its retries, and watched by the watchdog, which reads the same tuple."""
    assert JobKind.PROTECTIVE_STOP_WATCH in RECURRING_KINDS


def test_the_existing_chains_are_still_seeded() -> None:
    assert {
        JobKind.RESERVATION_SWEEP,
        JobKind.BALANCE_SYNC,
        JobKind.RECONCILIATION_SCAN,
        JobKind.JOBS_PURGE,
        JobKind.WATCHDOG_CHECK,
        JobKind.RECONCILIATION_PREPARE_BOOKING,
    } <= set(RECURRING_KINDS)
    assert len(set(RECURRING_KINDS)) == len(RECURRING_KINDS)


def test_the_composition_root_registers_a_handler_for_it() -> None:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)

    assert "JobKind.PROTECTIVE_STOP_WATCH: handle_protective_stop_watch" in source


def test_the_reconciliation_scan_is_built_with_the_resting_stops_it_leaves_to_the_watcher() -> None:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_scan") :]
    body = body[: body.index("async def handle_reconciliation_prepare_booking")]

    assert "resting_stops=RestingStopsAdapter(session)" in body


def test_the_interval_is_thirty_seconds_and_belongs_to_the_settings() -> None:
    """Shorter than twice the reconciliation scan, so a fired stop is booked before two
    scans could confirm the position it closed."""
    interval = Settings.model_fields["protective_stop_watch_interval_seconds"]

    assert interval.default == 30.0
    assert interval.default < 2 * Settings.model_fields[
        "reconciliation_scan_interval_seconds"
    ].default


def test_the_handler_is_wired_with_the_settings_interval_and_no_dry_run_skip() -> None:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_protective_stop_watch") :]
    body = body[: body.index("async def handle_", 10)]
    composed = inspect.getsource(main._build_protective_stop_watch)

    assert "settings.protective_stop_watch_interval_seconds" in composed
    # A resting stop belongs to a real position, which is watched whatever the brake says.
    assert "dry_run" not in body and "dry_run" not in composed

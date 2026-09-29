"""Decision 28 wiring: the guard runs at worker startup, AFTER the alert bridge
exists and BEFORE anything can claim a job.

Structural assertions, in the same spirit as ``test_watchdog_wiring`` and
``test_alerting``: ``worker.run`` cannot be exercised without a live database
and a real master key, so what is pinned here is that the wiring does not
quietly disappear or move. The behaviour behind it is proven separately: the
decision in ``tests/execution/domain/test_mode_origin.py``, the ERROR reaching
the alert channel in ``tests/execution/application/test_assert_mode_matches_ledger.py``,
and the composed check on real PostgreSQL in
``tests/ledger/infrastructure/test_mode_guard_startup_integration.py``.
"""

import inspect

from strategy_manager import main, worker


def test_the_worker_runs_the_guard_before_it_builds_the_composition_root() -> None:
    """Before ``build_worker_runner`` because that is where the adapter is
    chosen from ``DRY_RUN`` and where ``WorkerRunner`` is created: a refusal
    after it would already have registered handlers, and one after the
    seeding would already have queued jobs for the wrong mode."""
    source = inspect.getsource(worker._run_worker)

    assert "assert_dry_run_matches_ledger(dry_run=settings.dry_run)" in source
    assert source.index("assert_dry_run_matches_ledger") < source.index(
        "build_worker_runner("
    )
    assert source.index("assert_dry_run_matches_ledger") < source.index(
        "_seed_recurring_chains(settings)"
    )
    assert source.index("assert_dry_run_matches_ledger") < source.index("run_forever")


def test_the_guard_runs_inside_the_alert_bridge() -> None:
    """The ERROR only reaches Telegram if the bridge is installed when it is
    logged. ``run`` installs it, then calls ``_run_worker`` inside the context,
    and the guard is called from ``_run_worker``."""
    source = inspect.getsource(worker.run)

    assert "async with operator_alerts(settings) as bridge:" in source
    assert source.index("operator_alerts(settings)") < source.index(
        "_run_worker(settings, bridge)"
    )
    # ``_run_worker`` is the only caller, so nothing can run the guard outside
    # the ``operator_alerts`` context.
    assert "assert_dry_run_matches_ledger" not in source


def test_a_refusal_is_not_swallowed_on_the_way_out_of_the_worker() -> None:
    """The exit mechanism is the exception itself, like every other startup
    invariant: ``main`` catches ``KeyboardInterrupt`` and nothing else, so an
    ``InvariantViolation`` ends the process with a non-zero status."""
    source = inspect.getsource(worker.main)

    assert "except KeyboardInterrupt" in source
    assert "except Exception" not in source
    assert "except InvariantViolation" not in source
    assert "sys.exit(0)" not in source


def test_the_composition_root_wires_the_sql_reader_to_the_use_case() -> None:
    source = inspect.getsource(main.assert_dry_run_matches_ledger)

    assert "SqlAlchemyModeOriginReader" in source
    assert "assert_mode_matches_ledger" in source

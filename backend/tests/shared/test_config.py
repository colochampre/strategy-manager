"""Defaults for the reconciliation settings (design.md § Configuration).

``RECONCILIATION_SCAN_INTERVAL_SECONDS`` is not a guess: Phase 0 measured it
live against both venues (scripts/measure_reconciliation_rate_limits.py) and
found the binding constraint is staleness/false-confirmation tolerance, not
either venue's rate limit — see ``config.py`` for the full arithmetic.
"""

from strategy_manager.shared.config import Settings


def test_reconciliation_scan_interval_defaults_to_thirty_seconds() -> None:
    assert Settings().reconciliation_scan_interval_seconds == 30.0


def test_reconciliation_confirmations_defaults_to_two() -> None:
    assert Settings().reconciliation_confirmations == 2

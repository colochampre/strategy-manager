"""The watchdog is only a watchdog if something actually runs it.

Structural assertions, and deliberate ones, in the same spirit as
``test_alerting``'s: the composition inside ``build_worker_runner`` and
``worker.run`` cannot be exercised without a live database and a real master
key, so what is pinned here is that the wiring does not quietly disappear.

The failure mode these prevent is specific and silent. A ``watchdog.check``
job with no registered handler is FAILed by ``WorkerRunner`` on every claim,
spends its five attempts and leaves the chain dead — so the one job whose
purpose is to notice a dead chain would be the dead chain, and nothing would
say so.
"""

import inspect

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.recurring_jobs import RECURRING_KINDS


def test_the_watchdog_is_one_of_the_seeded_recurring_chains() -> None:
    """Seeded at startup like the others, and revived by
    ``RecurringChainRevival`` if it ever exhausts its retries — which is the
    only self-healing this chain can have."""
    assert JobKind.WATCHDOG_CHECK in RECURRING_KINDS


def test_the_composition_root_registers_a_handler_for_it() -> None:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)

    assert "JobKind.WATCHDOG_CHECK: handle_watchdog_check" in source


def test_the_watchdog_handler_never_reaches_a_venue() -> None:
    """The check reads the DATABASE ONLY. A watchdog that can hang on an
    exchange's socket stops watching exactly when something is wrong, and its
    own failure would then take its chain down."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_watchdog_check") :]
    body = body[: body.index("async def queue_factory")]

    assert "read_only_client" not in body
    assert "trade_client" not in body
    assert "CredentialVault" not in body


def test_the_worker_hands_its_alert_bridge_to_the_composition_root() -> None:
    """Condition 4 — a lossy alert channel — is unanswerable without the live
    bridge, and the bridge only exists inside ``operator_alerts``."""
    from strategy_manager import worker

    assert "alert_channel=alert_channel" in inspect.getsource(worker._run_worker)
    assert "_run_worker(settings, bridge)" in inspect.getsource(worker.run)

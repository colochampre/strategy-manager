"""``reconciliation.prepare_booking`` is only a recurring chain if something
actually seeds it, watches it, and runs it (Unit 5, mirrors
``test_watchdog_wiring.py``'s own structural style exactly).

The failure mode these prevent is specific and silent, the same one that
motivated the watchdog itself: a job kind with no registered handler is
FAILed by ``WorkerRunner`` on every claim, spends its five attempts, and
leaves the chain dead -- so a booking chain that never prepares anything
would look identical to one deployment with zero discrepancies, and nothing
would say so.
"""

import inspect

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.recurring_jobs import RECURRING_KINDS


def test_the_kind_is_one_of_the_seeded_recurring_chains() -> None:
    """Seeded at startup like the others, and revived by
    ``RecurringChainRevival`` if it ever exhausts its retries."""
    assert JobKind.RECONCILIATION_PREPARE_BOOKING in RECURRING_KINDS


def test_the_watchdog_reads_the_same_tuple_the_seeder_does() -> None:
    """``main.py`` wires the SAME ``RECURRING_KINDS`` into ``Watchdog``'s own
    constructor -- so "should be scheduled" means one thing in this system,
    not two, and a dead booking chain is reported exactly like a dead scan
    chain."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    assert "recurring_kinds=RECURRING_KINDS" in source


def test_the_composition_root_registers_a_handler_for_it() -> None:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)

    assert (
        "JobKind.RECONCILIATION_PREPARE_BOOKING: handle_reconciliation_prepare_booking"
        in source
    )


def test_a_real_fill_reader_is_never_built_under_dry_run() -> None:
    """Mirrors ``handle_reconciliation_scan``'s identical guard around its
    own venue POSITION readers: building a fill reader means decrypting a
    trade credential and opening a socket, and the handler never calls
    ``sweep()`` under DRY_RUN anyway."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_prepare_booking") :]
    body = body[: body.index("async def handle_jobs_purge")]

    assert "if not settings.dry_run:" in body


def test_the_bybit_fill_reader_uses_the_vault_credential() -> None:
    """Same credential source ``handle_reconciliation_scan`` already uses
    for the Bybit POSITION reader (design decision 9: "Credentials follow
    each venue's existing position-read precedent unchanged")."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_prepare_booking") :]
    body = body[: body.index("async def handle_jobs_purge")]

    assert "SqlAlchemyCredentialVault" in body
    assert "BybitVenueFillReader(" in body


def test_the_binance_fill_reader_uses_the_read_only_env_key() -> None:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_prepare_booking") :]
    body = body[: body.index("async def handle_jobs_purge")]

    assert "binance_credentials_from_settings(settings)" in body
    assert "BinanceVenueFillReader(" in body

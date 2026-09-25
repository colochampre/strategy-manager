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


def test_binance_booking_prepare_signs_with_vault_key_not_settings() -> None:
    """PR 3 (1b.6): decision 18 (ONE key per exchange) supersedes decision 9's
    Bybit-vault/Binance-``.env`` split -- Binance's fill reader now loads the
    SAME vault credential the Bybit fill reader just above already uses,
    never ``binance_credentials_from_settings(settings)``."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_prepare_booking") :]
    body = body[: body.index("async def handle_jobs_purge")]

    assert "BinanceVenueFillReader(" in body
    assert "binance_credentials_from_settings" not in body
    # Both venues' fill readers load through the vault in this block -- one
    # ``SqlAlchemyCredentialVault(...)`` construction for Bybit, another for
    # Binance -- and each is immediately followed by its own exchange load.
    assert body.count("SqlAlchemyCredentialVault(") >= 2
    assert "load(BINANCE_EXCHANGE)" in body


# --- 1b.2: the four remaining Binance read sites, each pinned the same way --
#
# ``build_worker_runner`` wires five separate Binance READ sites (design's own
# count in tasks.md's PR 3 file list). The booking-prepare site is pinned
# above; the other four get one test each below, sliced to their OWN nested
# function/block so a passing assertion cannot be satisfied by a DIFFERENT
# site's vault call leaking into a wider substring match.


def test_binance_balance_refresh_signs_with_vault_key() -> None:
    """``balance_refresh_reader_for``'s ``binance_reader`` factory (site
    ``main.py:756`` in tasks.md's file list) -- the on-demand pre-allocation
    refresh, mirroring its own Bybit sibling just above it."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def balance_refresh_reader_for") :]
    body = body[: body.index("async def venue_net_position_reader_for")]

    assert "async def binance_reader()" in body
    reader_body = body[body.index("async def binance_reader()") :]
    assert "binance_credentials_from_settings" not in reader_body
    assert "SqlAlchemyCredentialVault(" in reader_body
    assert "load(BINANCE_EXCHANGE)" in reader_body


def test_binance_venue_position_signs_with_vault_key() -> None:
    """``venue_net_position_reader_for``'s ``binance_position_reader`` factory
    (site ``main.py:822``) -- the Existing-Position Guard's divergent-branch
    read."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def venue_net_position_reader_for") :]
    body = body[: body.index("async def handle_signal_process")]

    assert "async def binance_position_reader()" in body
    reader_body = body[body.index("async def binance_position_reader()") :]
    assert "binance_credentials_from_settings" not in reader_body
    assert "SqlAlchemyCredentialVault(" in reader_body
    assert "load(BINANCE_EXCHANGE)" in reader_body


def test_binance_balance_sync_signs_with_vault_key() -> None:
    """``handle_balance_sync``'s Binance branch (site ``main.py:960``)."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_balance_sync") :]
    body = body[: body.index("async def handle_reservation_sweep")]

    assert "if binance_pools:" in body
    binance_block = body[body.index("if binance_pools:") :]
    assert "binance_credentials_from_settings" not in binance_block
    assert "SqlAlchemyCredentialVault(" in binance_block
    assert "load(BINANCE_EXCHANGE)" in binance_block


def test_binance_reconciliation_scan_signs_with_vault_key() -> None:
    """``handle_reconciliation_scan``'s Binance branch (site ``main.py:1039``)."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_scan") :]
    body = body[: body.index("async def handle_reconciliation_prepare_booking")]

    assert "if binance_pools:" in body
    binance_block = body[body.index("if binance_pools:") :]
    assert "binance_credentials_from_settings" not in binance_block
    assert "SqlAlchemyCredentialVault(" in binance_block
    assert "load(BINANCE_EXCHANGE)" in binance_block

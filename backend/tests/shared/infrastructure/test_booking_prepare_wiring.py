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
    # Per user (AD10): the handler hands the vault to the per-user helper, which
    # builds the reader.
    assert "_user_fill_readers(" in body
    assert "BybitVenueFillReader(" in inspect.getsource(main._user_fill_readers)


def test_binance_booking_prepare_signs_with_vault_key_not_settings() -> None:
    """PR 3 (1b.6): decision 18 (ONE key per exchange) supersedes decision 9's
    Bybit-vault/Binance-``.env`` split -- Binance's fill reader now loads the
    SAME vault credential the Bybit fill reader just above already uses,
    never ``binance_credentials_from_settings(settings)``."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_prepare_booking") :]
    body = body[: body.index("async def handle_jobs_purge")]

    helper = inspect.getsource(main._user_fill_readers)
    assert "BinanceVenueFillReader(" in helper
    assert "binance_credentials_from_settings" not in body
    assert "binance_credentials_from_settings" not in helper
    # One shared ``SqlAlchemyCredentialVault(...)`` construction serves both
    # venues (PR 3 unit 1b work unit 2's per-job active-key check needs the
    # SAME vault instance both branches load from) -- so the proof that both
    # actually load through it is each exchange's own ``vault.load(...)``
    # call, not a count of constructions.
    # Since multi-user design AD9 a load names its user too: each discrepancy's
    # own user (reconciliation per user's pool, AD10).
    assert "SqlAlchemyCredentialVault(" in body
    assert "vault.load(user_id, BYBIT_EXCHANGE)" in helper
    assert "vault.load(user_id, BINANCE_EXCHANGE)" in helper


# --- PR 15, cd.1.22: the worker books what it prepares (owner decision 66 Q1) --


def _prepare_booking_body() -> str:
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_prepare_booking") :]
    return body[: body.index("async def handle_jobs_purge")]


def test_the_automatic_step_is_wired_into_the_handler() -> None:
    body = _prepare_booking_body()

    assert "auto_book=AutoBookPending(" in body


def test_the_automatic_step_approves_with_the_use_case_the_route_built() -> None:
    """The worker builds ``ApproveBooking`` the way the route's
    ``_approve_use_case`` does (design § C2): the same adapters, the same fixed
    USD rate -- so a booking carries the same ``usd_rate_at_fill`` -- the same
    clock, and ``dry_run=settings.dry_run``."""
    body = _prepare_booking_body()
    assert "ApproveBooking(" in body, "the automatic step must build the approval use case"
    approve = "".join(body[body.index("ApproveBooking(") :].split())  # layout-insensitive

    assert "proposals=SqlAlchemyBookingProposalRepository(session)" in approve
    assert "discrepancies=SqlAlchemyDiscrepancyRepository(session)" in approve
    assert "InFlightCloseAdapter(SqlAlchemyExecutionAttemptRepository(session))" in approve
    assert "writer=SqlAlchemyBookingWriter(session)" in approve
    assert 'FixedUsdRateProvider({Currency.USDT:Decimal("1")})' in approve
    assert "clock=SystemClock()" in approve
    assert "commit=session" in approve
    assert "dry_run=settings.dry_run" in approve


def test_the_announcement_is_wired_with_the_grace_and_the_reminder_settings() -> None:
    body = "".join(_prepare_booking_body().split())

    assert "announce_needs_owner=AnnounceNeedsOwner(" in body
    announce = body[body.index("AnnounceNeedsOwner(") :]
    assert "discrepancies=SqlAlchemyDiscrepancyRepository(session)" in announce
    assert "approved=SqlAlchemyBookingProposalRepository(session)" in announce
    assert "clock=SystemClock()" in announce
    assert "grace_seconds=settings.reconciliation_auto_booking_grace_seconds" in announce
    assert "reminder_seconds=settings.reconciliation_needs_owner_reminder_seconds" in announce


def test_prepare_booking_receives_the_system_order_ids_adapter() -> None:
    """Owner decision 66 Q2: the refusal of a fill of an order this system
    placed must never be skipped, so the adapter is always passed."""
    body = _prepare_booking_body()

    assert "system_order_ids=SystemOrderIdsAdapter(session)" in body


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
    # The vault is constructed ONCE per job, ABOVE both nested factories (PR
    # 3 unit 1b work unit 2: the per-job active-key check needs the SAME
    # vault instance the factories load from) -- so the construction lives
    # in the WIDER site body, while the narrower factory body only proves
    # its own load call.
    assert "SqlAlchemyCredentialVault(" in body
    reader_body = body[body.index("async def binance_reader()") :]
    assert "binance_credentials_from_settings" not in reader_body
    # The job owner's key (AD8): ``owner`` is the strategy author.
    assert "vault.load(owner, BINANCE_EXCHANGE)" in reader_body


def test_binance_venue_position_signs_with_vault_key() -> None:
    """``venue_net_position_reader_for``'s ``binance_position_reader`` factory
    (site ``main.py:822``) -- the Existing-Position Guard's divergent-branch
    read."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def venue_net_position_reader_for") :]
    body = body[: body.index("async def handle_signal_process")]

    assert "async def binance_position_reader()" in body
    assert "SqlAlchemyCredentialVault(" in body
    reader_body = body[body.index("async def binance_position_reader()") :]
    assert "binance_credentials_from_settings" not in reader_body
    assert "vault.load(owner, BINANCE_EXCHANGE)" in reader_body


def test_binance_balance_sync_signs_with_vault_key() -> None:
    """``handle_balance_sync``'s Binance branch. Since multi-user design AD9
    every pair, Binance's included, is read through ``_open_balance_reader``
    with that pair's user's vault key."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_balance_sync") :]
    body = body[: body.index("async def handle_reservation_sweep")]
    opener = source[source.index("async def _open_balance_reader") :]
    opener = opener[: opener.index("async def exchange_for")]

    assert "SqlAlchemyCredentialVault(" in body
    assert "for exchange in (BYBIT_EXCHANGE, BINANCE_EXCHANGE):" in body
    assert "_open_balance_reader(" in body
    assert "binance_credentials_from_settings" not in opener
    assert "vault.load(user_id, exchange)" in opener
    assert "binance_read_only_client(" in opener


def test_binance_reconciliation_scan_signs_with_vault_key() -> None:
    """``handle_reconciliation_scan``'s Binance reader: since multi-user design
    AD10 it is built per user by ``_user_position_readers``, with that user's
    own vault key."""
    from strategy_manager import main

    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def handle_reconciliation_scan") :]
    body = body[: body.index("async def handle_reconciliation_prepare_booking")]
    helper = inspect.getsource(main._user_position_readers)

    assert "SqlAlchemyCredentialVault(" in body
    assert "_user_position_readers(" in body
    assert "binance_credentials_from_settings" not in helper
    assert "vault.load(user_id, BINANCE_EXCHANGE)" in helper
    assert "binance_read_only_client(" in helper

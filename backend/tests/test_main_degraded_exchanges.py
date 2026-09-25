"""PR 3 unit 1b, work unit 2: the per-job DEGRADED tracker (orchestrator's
binding correction, overriding tasks.md's original "caller skips registering
adapters" wording).

DEGRADED IS NOT A STARTUP SNAPSHOT. Every Binance/Bybit READ site re-checks
the vault's active-key listing (``hints()``, no decrypt) on its own per-job
cadence, so a key saved or deleted while the worker runs is seen on the next
job, not only after a restart -- the same correction F11 already forced onto
pool enablement (design.md's own orchestrator note), applied here to
credential presence.

``main._track_degraded_exchanges`` is the shared, process-lifetime state
machine every read site calls into: it logs an ERROR the moment a configured
exchange's key disappears, an INFO the moment it comes back, and NOTHING in
steady state -- both because a job runs every few seconds and an ERROR
reaching Telegram on every single one would drown the channel it exists to
protect, and because the worker's own startup already reported the same
condition once (``worker._assert_keys_present``, seeded into this tracker via
``initial_degraded`` so the very first per-job check never repeats it).
"""

import inspect
import logging

import pytest

from strategy_manager import main

_CONFIGURED = frozenset({"bybit", "binance"})


def _sliced(start_marker: str, end_marker: str) -> str:
    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index(start_marker) :]
    return body[: body.index(end_marker)]


def test_a_newly_degraded_exchange_logs_one_error_and_is_tracked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker: set[str] = set()

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=_CONFIGURED, active=frozenset({"bybit"})
        )

    assert tracker == {"binance"}
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "binance" in error_records[0].getMessage()


def test_a_recovered_exchange_logs_one_info_and_is_untracked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker: set[str] = {"binance"}

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=_CONFIGURED, active=frozenset({"bybit", "binance"})
        )

    assert tracker == set()
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert "binance" in info_records[0].getMessage()
    assert not any(r.levelno == logging.ERROR for r in caplog.records)


def test_steady_state_across_several_cycles_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The dedupe proof: an exchange already known DEGRADED must not be
    re-reported every cycle -- balance.sync alone runs every 60s, and an
    ERROR reaching Telegram on every one of them is exactly the flood this
    tracker exists to prevent."""
    tracker: set[str] = {"binance"}

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        for _ in range(5):
            main._track_degraded_exchanges(
                tracker, configured=_CONFIGURED, active=frozenset({"bybit"})
            )

    assert tracker == {"binance"}
    assert caplog.records == []


def test_a_seeded_startup_degraded_set_is_not_re_logged_on_the_first_check(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Seeded from ``worker._assert_keys_present``'s own startup ERROR
    (``build_worker_runner``'s ``initial_degraded``), so the exchange it
    already reported is not reported a second time by the first per-job
    check after boot."""
    tracker: set[str] = {"binance"}  # as if seeded from initial_degraded

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=_CONFIGURED, active=frozenset({"bybit"})
        )

    assert caplog.records == []


def test_two_configured_exchanges_missing_at_once_each_log_their_own_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Triangulation: not a single hardcoded 'binance' string -- BOTH
    exchanges must be named correctly when both lose their key at once."""
    tracker: set[str] = set()

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(tracker, configured=_CONFIGURED, active=frozenset())

    assert tracker == {"bybit", "binance"}
    error_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_messages) == 2
    assert any("bybit" in message for message in error_messages)
    assert any("binance" in message for message in error_messages)


# --- wiring pins: every read site decides PER JOB, from the active-key ------
# listing, never from a startup snapshot (the orchestrator's binding
# correction). Each site is sliced to its OWN nested function/block, exactly
# as PR 3's own unit-1 wiring tests do, so a passing assertion cannot be
# satisfied by a DIFFERENT site's call leaking into a wider substring match.


def test_balance_refresh_reader_gates_on_the_active_key_listing() -> None:
    body = _sliced(
        "async def balance_refresh_reader_for", "async def venue_net_position_reader_for"
    )

    assert "_active_exchanges(" in body
    assert "_track_degraded_exchanges(" in body
    assert "BYBIT_EXCHANGE in active" in body
    assert "BINANCE_EXCHANGE in active" in body


def test_venue_net_position_reader_gates_on_the_active_key_listing() -> None:
    body = _sliced("async def venue_net_position_reader_for", "async def handle_signal_process")

    assert "_active_exchanges(" in body
    assert "_track_degraded_exchanges(" in body
    assert "BYBIT_EXCHANGE in active" in body
    assert "BINANCE_EXCHANGE in active" in body


def test_balance_sync_gates_on_the_active_key_listing_before_building_syncs() -> None:
    """This is the urgent fix itself: a missing Binance key must never raise
    BEFORE ``handler.handle(job)`` runs, or the successor enqueue -- owned
    entirely by ``handler.handle`` -- never happens and the recurring chain
    dies."""
    body = _sliced("async def handle_balance_sync", "async def handle_reservation_sweep")

    assert "_active_exchanges(" in body
    assert "_track_degraded_exchanges(" in body
    assert "BYBIT_EXCHANGE in active" in body
    assert "BINANCE_EXCHANGE in active" in body


def test_reconciliation_scan_gates_on_the_active_key_listing() -> None:
    """Must filter the DEGRADED exchange's pools out of the list handed to
    ``ScanPools``, not only skip building its reader: ``ScanPools`` never
    swallows ``UnservedPoolError`` (only ``VenuePositionReadError``), so a
    pool with no registered reader would kill this chain exactly like the
    balance.sync bug this unit fixes."""
    body = _sliced(
        "async def handle_reconciliation_scan", "async def handle_reconciliation_prepare_booking"
    )

    assert "_active_exchanges(" in body
    assert "_track_degraded_exchanges(" in body
    # Pools filtered OUT of the list before ScanPools ever sees them, not
    # gated inline while building readers -- both collections must agree by
    # construction, or an unregistered pool raises UnservedPoolError.
    assert "BYBIT_EXCHANGE not in active" in body
    assert "bybit_pools = []" in body
    assert "BINANCE_EXCHANGE not in active" in body
    assert "binance_pools = []" in body


def test_booking_prepare_registers_a_degraded_stand_in_reader() -> None:
    """``PrepareBooking.sweep`` reads discrepancies straight from the
    database, not from a pool list this composition root controls, so a
    CONFIRMED discrepancy on a now-DEGRADED exchange can still be swept.
    Omitting the reader entirely would raise ``UnservedFillPoolError``,
    which ``sweep`` does NOT swallow -- so a DEGRADED exchange gets a
    stand-in reader that raises the ``VenueFillReadError`` sweep already
    tolerates per discrepancy, instead of no reader at all."""
    body = _sliced(
        "async def handle_reconciliation_prepare_booking", "async def handle_jobs_purge"
    )

    assert "_active_exchanges(" in body
    assert "_track_degraded_exchanges(" in body
    assert "_DegradedVenueFillReader(" in body


# --- _DegradedVenueFillReader: the stand-in itself --------------------------


async def test_degraded_venue_fill_reader_claims_its_exchange_and_venues() -> None:
    """The registry routes by ``(exchange, venue)``, read off these two
    attributes -- get them wrong and the stand-in either claims nothing
    (``UnservedFillPoolError`` returns) or claims the WRONG exchange's pool."""
    reader = main._DegradedVenueFillReader("binance", frozenset({"usdt-m"}))

    assert reader.exchange == "binance"
    assert reader.venues == frozenset({"usdt-m"})


async def test_degraded_venue_fill_reader_raises_the_swallowable_error() -> None:
    """MUST be ``VenueFillReadError`` (what ``PrepareBooking.sweep`` already
    swallows per discrepancy), never ``UnservedFillPoolError`` (never
    swallowed, kills the chain) and never a bare/unrelated exception (also
    never swallowed)."""
    from datetime import UTC, datetime

    from strategy_manager.reconciliation.application.ports import VenueFillReadError

    reader = main._DegradedVenueFillReader("binance", frozenset({"usdt-m"}))
    now = datetime(2026, 9, 25, tzinfo=UTC)

    with pytest.raises(VenueFillReadError, match="binance"):
        await reader.fills_in_window(("binance", "usdt-m", "USDT"), "BTCUSDT", now, now)

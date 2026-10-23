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
from uuid import UUID

import pytest

from strategy_manager import main
from tests.owner import OWNER_ID

# Pairs since multi-user design AD9: ``(user_id, exchange)``.
BYBIT = (OWNER_ID, "bybit")
BINANCE = (OWNER_ID, "binance")
OTHER_ID = UUID("5ec0d0b2-0000-4000-8000-0000000000b2")
_CONFIGURED = frozenset({BYBIT, BINANCE})


def _sliced(start_marker: str, end_marker: str) -> str:
    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index(start_marker) :]
    return body[: body.index(end_marker)]


def test_a_newly_degraded_exchange_logs_one_error_and_is_tracked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker: set[tuple[UUID, str]] = set()

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=_CONFIGURED, active=frozenset({BYBIT})
        )

    assert tracker == {BINANCE}
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "binance" in error_records[0].getMessage()
    assert str(OWNER_ID)[:8] in error_records[0].getMessage()


def test_one_users_missing_key_degrades_only_that_users_pair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AD9: the owner and another user each hold a Bybit pool; only the owner
    holds a key. The other user's pair alone is degraded, and the ERROR names
    their id prefix, never an e-mail and never the owner's."""
    tracker: set[tuple[UUID, str]] = set()

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker,
            configured=frozenset({BYBIT, (OTHER_ID, "bybit")}),
            active=frozenset({BYBIT}),
        )

    assert tracker == {(OTHER_ID, "bybit")}
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "5ec0d0b2" in errors[0]
    assert str(OWNER_ID)[:8] not in errors[0]
    assert "@" not in errors[0]


def test_a_recovered_exchange_logs_one_info_and_is_untracked(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracker: set[tuple[UUID, str]] = {BINANCE}

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=_CONFIGURED, active=frozenset({BYBIT, BINANCE})
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
    tracker: set[tuple[UUID, str]] = {BINANCE}

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        for _ in range(5):
            main._track_degraded_exchanges(
                tracker, configured=_CONFIGURED, active=frozenset({BYBIT})
            )

    assert tracker == {BINANCE}
    assert caplog.records == []


def test_a_seeded_startup_degraded_set_is_not_re_logged_on_the_first_check(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Seeded from ``worker._assert_keys_present``'s own startup ERROR
    (``build_worker_runner``'s ``initial_degraded``), so the exchange it
    already reported is not reported a second time by the first per-job
    check after boot."""
    tracker: set[tuple[UUID, str]] = {BINANCE}  # as if seeded from initial_degraded

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=_CONFIGURED, active=frozenset({BYBIT})
        )

    assert caplog.records == []


def test_two_configured_exchanges_missing_at_once_each_log_their_own_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Triangulation: not a single hardcoded 'binance' string -- BOTH
    exchanges must be named correctly when both lose their key at once."""
    tracker: set[tuple[UUID, str]] = set()

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(tracker, configured=_CONFIGURED, active=frozenset())

    assert tracker == {BYBIT, BINANCE}
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

    assert "read_key_coverage(session)" in body
    assert "_track_degraded_exchanges(" in body
    # The job owner's own pair, never the exchange alone (AD9).
    assert "(owner, BYBIT_EXCHANGE) in active" in body
    assert "(owner, BINANCE_EXCHANGE) in active" in body


def test_venue_net_position_reader_gates_on_the_active_key_listing() -> None:
    body = _sliced("async def venue_net_position_reader_for", "async def handle_signal_process")

    assert "read_key_coverage(session)" in body
    assert "_track_degraded_exchanges(" in body
    assert "(owner, BYBIT_EXCHANGE) in active" in body
    assert "(owner, BINANCE_EXCHANGE) in active" in body


def test_balance_sync_gates_on_the_active_key_listing_before_building_syncs() -> None:
    """This is the urgent fix itself: a missing Binance key must never raise
    BEFORE ``handler.handle(job)`` runs, or the successor enqueue -- owned
    entirely by ``handler.handle`` -- never happens and the recurring chain
    dies."""
    body = _sliced("async def handle_balance_sync", "async def handle_reservation_sweep")

    assert "read_key_coverage(session)" in body
    assert "_track_degraded_exchanges(" in body
    # One sync per pair holding an active key (AD9), both exchanges.
    assert "for exchange in (BYBIT_EXCHANGE, BINANCE_EXCHANGE):" in body
    assert "if (user_id, exchange) not in active:" in body


def test_reconciliation_scan_gates_on_the_active_key_listing() -> None:
    """Must filter the DEGRADED exchange's pools out of the list handed to
    ``ScanPools``, not only skip building its reader: ``ScanPools`` never
    swallows ``UnservedPoolError`` (only ``VenuePositionReadError``), so a
    pool with no registered reader would kill this chain exactly like the
    balance.sync bug this unit fixes."""
    body = _sliced(
        "async def handle_reconciliation_scan", "async def handle_reconciliation_prepare_booking"
    )

    assert "read_key_coverage(session)" in body
    assert "_track_degraded_exchanges(" in body
    # Pools filtered OUT of the list before ScanPools ever sees them, not
    # gated inline while building readers -- both collections must agree by
    # construction, or an unregistered pool raises UnservedPoolError. Since
    # AD9 the filter is the key holder's own markets: none when nobody holds
    # an active key (``_markets_of`` with ``None``).
    assert (
        "bybit_pools = _markets_of(pool_set.by_key, bybit_holder, BYBIT_EXCHANGE)" in body
    )
    assert (
        "binance_pools = _markets_of(pool_set.by_key, binance_holder, BINANCE_EXCHANGE)"
        in body
    )


def test_a_market_with_no_key_holder_is_filtered_out_entirely() -> None:
    """The filter above, behaviorally: no holder, no markets; a holder, only
    that holder's markets, sorted."""
    market = ("bybit", "usdt-m", "USDT")
    by_key: dict[tuple[UUID, tuple[str, str, str]], object] = {
        (OWNER_ID, market): object(),
        (OTHER_ID, ("bybit", "coin-m", "BTC")): object(),
    }

    assert main._markets_of(by_key, None, "bybit") == []  # type: ignore[arg-type]
    assert main._markets_of(by_key, OWNER_ID, "bybit") == [market]  # type: ignore[arg-type]


def test_the_reconciliation_key_holder_is_a_user_with_a_pool_and_a_key_there() -> None:
    """INTERIM until B.8: the lowest id among users holding BOTH an enabled
    pool and an active key on the exchange; ``None`` when nobody does. A key
    alone, or a pool alone, never makes a holder."""
    market = ("bybit", "usdt-m", "USDT")
    pool_only = UUID("00000000-0000-4000-8000-000000000001")
    by_key: dict[tuple[UUID, tuple[str, str, str]], object] = {
        (pool_only, market): object(),
        (OWNER_ID, market): object(),
        (OTHER_ID, market): object(),
    }
    active = frozenset({(OWNER_ID, "bybit"), (OTHER_ID, "bybit"), (pool_only, "binance")})

    holder = main._reconciliation_key_holder(by_key, active, "bybit")  # type: ignore[arg-type]
    nobody = main._reconciliation_key_holder(by_key, active, "binance")  # type: ignore[arg-type]

    assert holder == OWNER_ID  # "0a1b..." sorts before "5ec0..."
    assert nobody is None


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

    assert "read_key_coverage(session)" in body
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

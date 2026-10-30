"""PR 3 unit 1b, work unit 3: the per-cycle pool reload (design.md's F11
correction, binding for this unit).

F11 argued that reading ``capital_pools.enabled`` only at startup was safe.
That held only in the DISABLE direction. In the ENABLE direction it broke
decision 21's primary flow silently: a key saved for a new exchange enables
its pool in the database, but the running worker never started reading it,
and every opening signal was refused as a stale/absent balance until someone
happened to restart the worker.

``_PoolSet`` is the shared, mutable, process-lifetime holder every consumer
in ``build_worker_runner`` reads through. It is refreshed ONLY by
``handle_balance_sync``, on its own ~60s cadence, rather than by every job
independently: ``signal.process`` runs once per claimed signal -- far more
often than an operator ever changes which pools are enabled -- and a fresh
``CapitalPoolRepository.list_enabled()`` query on every one of them would be
needless DB load for a change that happens, at most, a few times a day.
"""

import inspect
import logging
from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager import main
from strategy_manager.accounts.domain.pool_config import PoolConfig
from strategy_manager.shared.domain.money import Currency, Exchange, Venue
from tests.owner import OWNER_ID


def _sliced(start_marker: str, end_marker: str) -> str:
    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index(start_marker) :]
    return body[: body.index(end_marker)]

_BYBIT_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    user_id=OWNER_ID,
    min_order_size=Decimal("10"),
)
_BINANCE_POOL = PoolConfig(
    exchange=Exchange.BINANCE,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    user_id=OWNER_ID,
    min_order_size=Decimal("10"),
)
_OTHER_ID = UUID("00000000-0000-4000-8000-0000000000b2")
_OTHER_BYBIT_POOL = PoolConfig(
    exchange=Exchange.BYBIT,
    venue=Venue.USDT_M,
    settlement_currency=Currency.USDT,
    user_id=_OTHER_ID,
    min_order_size=Decimal("20"),
)

_BYBIT_KEY = (OWNER_ID, ("bybit", "usdt-m", "USDT"))
_BINANCE_KEY = (OWNER_ID, ("binance", "usdt-m", "USDT"))
_OTHER_BYBIT_KEY = (_OTHER_ID, ("bybit", "usdt-m", "USDT"))


# --- _PoolSet: the shared holder ---------------------------------------------


def test_pool_set_indexes_by_exchange_venue_currency_at_construction() -> None:
    pool_set = main._PoolSet([_BYBIT_POOL])

    assert pool_set.pools == (_BYBIT_POOL,)
    assert pool_set.by_key == {_BYBIT_KEY: _BYBIT_POOL}
    assert pool_set.configured_exchanges == frozenset({"bybit"})


def test_two_users_pools_on_one_market_are_two_entries_never_one() -> None:
    """AD8: the market alone is not a pool's identity. Keyed by market only,
    the second user's pool would silently replace the first's, and every read
    of the first user's pool would answer with the other user's config."""
    pool_set = main._PoolSet([_BYBIT_POOL, _OTHER_BYBIT_POOL])

    assert pool_set.by_key == {_BYBIT_KEY: _BYBIT_POOL, _OTHER_BYBIT_KEY: _OTHER_BYBIT_POOL}
    assert pool_set.configured_exchanges == frozenset({"bybit"})


def test_another_users_newly_enabled_pool_on_a_known_market_logs_its_own_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_pool_changes(frozenset({_BYBIT_KEY}), frozenset({_BYBIT_KEY, _OTHER_BYBIT_KEY}))

    info_records = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert f"of user {str(_OTHER_ID)[:8]}" in info_records[0]


def test_pool_set_replace_adopts_a_wider_pool_list() -> None:
    """Triangulation: a DIFFERENT input (two pools, two exchanges) must
    produce a DIFFERENT, correctly-widened result -- not the same output
    construction alone would already produce."""
    pool_set = main._PoolSet([_BYBIT_POOL])

    pool_set.replace([_BYBIT_POOL, _BINANCE_POOL])

    assert pool_set.pools == (_BYBIT_POOL, _BINANCE_POOL)
    assert pool_set.by_key == {_BYBIT_KEY: _BYBIT_POOL, _BINANCE_KEY: _BINANCE_POOL}
    assert pool_set.configured_exchanges == frozenset({"bybit", "binance"})


def test_pool_set_replace_can_shrink_back_to_one_exchange() -> None:
    pool_set = main._PoolSet([_BYBIT_POOL, _BINANCE_POOL])

    pool_set.replace([_BYBIT_POOL])

    assert pool_set.pools == (_BYBIT_POOL,)
    assert pool_set.by_key == {_BYBIT_KEY: _BYBIT_POOL}
    assert pool_set.configured_exchanges == frozenset({"bybit"})


def test_pool_set_replace_to_empty_is_the_zero_pools_case() -> None:
    """Binding requirement 5: zero enabled pools at runtime must be a valid,
    adoptable state -- not a refusal. That refusal belongs to the STARTUP
    guard only (``worker._run_worker``'s ``if not pools: raise``), never
    re-checked here."""
    pool_set = main._PoolSet([_BYBIT_POOL])

    pool_set.replace([])

    assert pool_set.pools == ()
    assert pool_set.by_key == {}
    assert pool_set.configured_exchanges == frozenset()


# --- _track_pool_changes: the enable/disable transition log ------------------


def test_a_newly_enabled_pool_logs_one_info(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_pool_changes(frozenset({_BYBIT_KEY}), frozenset({_BYBIT_KEY, _BINANCE_KEY}))

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    assert "binance" in info_records[0].getMessage()
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_a_newly_disabled_pool_logs_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_pool_changes(frozenset({_BYBIT_KEY, _BINANCE_KEY}), frozenset({_BYBIT_KEY}))

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "binance" in warning_records[0].getMessage()
    assert not any(r.levelno == logging.INFO for r in caplog.records)


def test_steady_state_pool_set_logs_nothing_across_several_cycles(
    caplog: pytest.LogCaptureFixture,
) -> None:
    same = frozenset({_BYBIT_KEY, _BINANCE_KEY})

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        for _ in range(5):
            main._track_pool_changes(same, same)

    assert caplog.records == []


def test_seeded_from_the_startup_set_the_first_reload_logs_nothing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The 'seed from the startup set' requirement: comparing the STARTUP
    pool set to an UNCHANGED reload must not manufacture a transition."""
    startup = frozenset({_BYBIT_KEY})

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_pool_changes(startup, startup)

    assert caplog.records == []


# --- _track_degraded_exchanges: drop a de-configured exchange silently ------


def test_an_exchange_with_no_configured_pool_left_is_dropped_without_an_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Binding requirement 3: when an exchange's LAST pool is disabled, it
    must leave the DEGRADED tracker -- but silently, never with the
    "reads resume" INFO ``_track_degraded_exchanges`` logs for an actual
    recovery. It did not recover; it stopped mattering."""
    # Pairs since multi-user design AD9.
    tracker = {(OWNER_ID, "binance")}  # still degraded, but no longer configured below

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker, configured=frozenset({(OWNER_ID, "bybit")}), active=frozenset()
        )

    assert (OWNER_ID, "binance") not in tracker
    assert not any("resume" in record.getMessage() for record in caplog.records)


def test_a_degraded_exchange_still_configured_is_not_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Triangulation: the cleanup must be scoped to exchanges that left
    ``configured`` entirely, never a blanket wipe of the tracker."""
    tracker = {(OWNER_ID, "binance")}

    with caplog.at_level(logging.INFO, logger="strategy_manager.main"):
        main._track_degraded_exchanges(
            tracker,
            configured=frozenset({(OWNER_ID, "bybit"), (OWNER_ID, "binance")}),
            active=frozenset({(OWNER_ID, "bybit")}),
        )

    assert (OWNER_ID, "binance") in tracker


# --- wiring pins: balance.sync is the ONE reload point, every other site ----
# reads the SAME shared ``pool_set`` instead of a frozen startup snapshot.


def test_balance_sync_reloads_the_pool_set_before_anything_else() -> None:
    body = _sliced("async def handle_balance_sync", "async def handle_reservation_sweep")

    assert "_reload_pools(" in body
    assert "pool_set.by_key" in body
    assert "pools_by_key" not in body  # the old frozen-snapshot name must be gone


def test_reload_pools_keeps_the_previous_set_on_a_lock_key_collision() -> None:
    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("async def _reload_pools") :]
    body = body[: body.index("async def handle_signal_process")]

    assert "PoolLockKeyCollisionError" in body
    assert "assert_pool_lock_keys_distinct(" in body
    assert "pool_set.replace(" in body
    # The collision branch must return/skip BEFORE ``pool_set.replace`` --
    # sliced ordering proves it rather than merely both strings existing
    # somewhere in the function.
    assert body.index("PoolLockKeyCollisionError") < body.index("pool_set.replace(")


def test_balance_refresh_reader_reads_the_shared_pool_set() -> None:
    body = _sliced(
        "async def balance_refresh_reader_for", "async def venue_net_position_reader_for"
    )
    assert "pool_set.by_key" in body
    assert "pools_by_key" not in body


def test_venue_net_position_reader_reads_the_shared_pool_set() -> None:
    body = _sliced("async def venue_net_position_reader_for", "async def handle_signal_process")
    assert "pool_set.by_key" in body
    assert "pools_by_key" not in body


def test_reconciliation_scan_reads_the_shared_pool_set() -> None:
    body = _sliced(
        "async def handle_reconciliation_scan", "async def handle_reconciliation_prepare_booking"
    )
    assert "pool_set.by_key" in body
    assert "pools_by_key" not in body


def test_booking_prepare_reads_the_shared_pool_set() -> None:
    body = _sliced("async def handle_reconciliation_prepare_booking", "async def handle_jobs_purge")
    assert "pool_set.by_key" in body
    assert "pools_by_key" not in body


def test_signal_process_reads_the_shared_pool_set() -> None:
    body = _sliced("async def handle_signal_process", "async def handle_signal_open_after_close")
    assert "pool_set.by_key" in body


def test_no_frozen_pools_by_key_snapshot_survives_anywhere_in_the_composition_root() -> None:
    """The strongest form of the pin: the OLD name must not exist anywhere
    in ``build_worker_runner`` any more -- every consumer identified in the
    unit's own consumer map was migrated, not just the five read sites."""
    source = inspect.getsource(main.build_worker_runner)
    assert "pools_by_key" not in source


def test_the_degraded_check_reads_pools_and_keys_in_one_query_everywhere() -> None:
    """Deleting a key from the panel disables its pool in the same commit, but
    the shared pool set only catches up on the next balance.sync reload. Fed
    from it, the tracker saw an enabled pool with no key and sent a false ERROR
    to Telegram (2026-10-21, after Bybit's key was deleted). Every call now
    takes both sets from ONE statement, so it never mixes two moments."""
    source = inspect.getsource(main.build_worker_runner)
    assert "configured_exchanges = frozenset" not in source
    assert "configured=pool_set.configured_exchanges" not in source
    assert "_active_exchanges(" not in source
    assert source.count("coverage = await read_key_coverage(session)") >= 5
    assert source.count("configured=coverage.configured") >= 5


def test_dry_run_fakes_cover_both_bybit_and_binance_unconditionally() -> None:
    """Binding requirement 6: a pool enabled later on an exchange NOT
    present in the startup pool list must still have a DRY_RUN adapter --
    otherwise ``exchange_for``'s DRY_RUN branch and
    ``venue_net_position_reader_for``'s DRY_RUN branch have nothing to
    yield for it."""
    source = inspect.getsource(main.build_worker_runner)
    body = source[source.index("fakes_by_exchange = {") :]
    body = body[: body.index("simulated_venues = SimulatedVenues(")]

    assert "BYBIT_EXCHANGE" in body
    assert "BINANCE_EXCHANGE" in body

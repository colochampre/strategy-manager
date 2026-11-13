"""``ScanPools`` leaves a fired stop to the stop watcher (subscriber-safety SS.7).

A protective stop that fires closes a position at the venue and this system never submitted
the order, so for a moment the venue is flat while the ledger still holds the position. The
stop watcher books the stop's fills; until it has decided, the scan must not count that
moment towards a confirmation, or a position the system itself protected would raise a
discrepancy alert and a booking proposal.

The hold is the NARROW case only: the venue is flat, the ledger holds the market, and a stop
for it is still RESTING. Every other mismatch is classified, counted and confirmed exactly as
before, and a stop the watcher wrongly read GONE falls back to today's path.

The market wears three spellings across the boundary: the stop records TradingView's
``DOGEUSDT.P``, the venue reports ``DOGEUSDT`` and the ledger holds ``DOGEUSDT.P``.
"""

import logging
from decimal import Decimal
from uuid import uuid4

import pytest

from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
)
from strategy_manager.reconciliation.domain.positions import (
    LedgerPosition,
    OpenAllocation,
    VenuePosition,
)
from tests.reconciliation.application import test_scan_pools as fakes

POOL = fakes.POOL_A
USER = fakes._user_of(POOL)
ALERT_SPELLING = "DOGEUSDT.P"
VENUE_SPELLING = "DOGEUSDT"
_SCANNER = "strategy_manager.reconciliation.application.scan_pools"


def _build(
    *,
    venue: list[VenuePosition],
    ledger: list[LedgerPosition],
    resting: dict[tuple, list[str]] | None = None,
    open_rows: list | None = None,
) -> tuple[ScanPools, fakes.FakeDiscrepancyRepository, fakes.FakeRestingStops]:
    discrepancies = fakes.FakeDiscrepancyRepository({POOL: open_rows} if open_rows else None)
    stops = fakes.FakeRestingStops(resting)
    use_case = ScanPools(
        pools=[POOL],
        pool_users={POOL: USER},
        venue_readers=fakes.FakeVenueReaderRegistry(
            {("bybit", "usdt-m"): fakes.FakeVenueReader(venue)}
        ),
        ledger_positions=fakes.FakeLedgerPositions({POOL: ledger}),
        discrepancies=discrepancies,
        clock=fakes.FrozenClock(fakes.NOW),
        commit=fakes.SpyCommit(),
        confirmations_required=2,
        resting_stops=stops,
    )
    return use_case, discrepancies, stops


def _held(quantity: str = "76") -> list[LedgerPosition]:
    return [
        LedgerPosition(ALERT_SPELLING, (OpenAllocation(uuid4(), Decimal(quantity)),)),
    ]


async def test_a_flat_venue_beside_a_resting_stop_is_left_to_the_watcher(
    caplog: pytest.LogCaptureFixture,
) -> None:
    use_case, discrepancies, stops = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("0"))],
        ledger=_held(),
        resting={(USER, POOL): [ALERT_SPELLING]},
    )

    with caplog.at_level(logging.INFO, logger=_SCANNER):
        result = await use_case.scan(uuid4())

    # No row opened, nothing counted, nothing resolved, and no confirmation warning.
    assert discrepancies.upserts == []
    assert discrepancies.resolves == []
    assert (result.discrepancies_opened, result.discrepancies_resolved) == (0, 0)
    assert stops.asked == [(USER, POOL)]
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    [line] = [r.getMessage() for r in caplog.records if "stop watcher" in r.getMessage()]
    # Named by the market key the scan compares under, never by either side's spelling.
    assert VENUE_SPELLING in line and "bybit/usdt-m/USDT" in line


async def test_a_venue_that_reports_no_row_at_all_for_the_market_is_flat_too() -> None:
    """Venues omit a flat market from their position list: absent is flat."""
    use_case, discrepancies, _ = _build(
        venue=[], ledger=_held(), resting={(USER, POOL): [ALERT_SPELLING]}
    )

    await use_case.scan(uuid4())

    assert discrepancies.upserts == []


async def test_a_row_already_open_is_neither_advanced_nor_resolved_while_the_stop_rests() -> None:
    """The count stays where it was. Held for a tick, not forgiven: if the stop is read GONE
    the next scans carry on from the count the row had."""
    row = fakes._record(
        POOL,
        VENUE_SPELLING,
        DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        Decimal("0"),
        Decimal("76"),
        consecutive_scans=1,
    )
    use_case, discrepancies, _ = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("0"))],
        ledger=_held(),
        resting={(USER, POOL): [ALERT_SPELLING]},
        open_rows=[row],
    )

    result = await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert discrepancies.resolves == []
    assert result.discrepancies_opened == 0


async def test_without_a_resting_stop_the_same_mismatch_opens_as_it_always_did() -> None:
    use_case, discrepancies, stops = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("0"))], ledger=_held()
    )

    result = await use_case.scan(uuid4())

    [(_, symbol, observation, _, consecutive_scans, status, _, _)] = discrepancies.upserts
    assert symbol == VENUE_SPELLING
    assert observation.kind is DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE
    assert (consecutive_scans, status) == (1, DiscrepancyStatus.OBSERVED)
    assert result.discrepancies_opened == 1
    assert stops.asked == [(USER, POOL)]


async def test_a_stop_wrongly_read_gone_falls_back_to_confirming_the_discrepancy() -> None:
    """Fired with its fills not yet published and read GONE: the stop is no longer RESTING,
    so the second scan confirms the row and today's alert and booking proposal take over."""
    previous = fakes._record(
        POOL,
        VENUE_SPELLING,
        DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        Decimal("0"),
        Decimal("76"),
        consecutive_scans=1,
    )
    use_case, discrepancies, _ = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("0"))],
        ledger=_held(),
        resting={},
        open_rows=[previous],
    )

    await use_case.scan(uuid4())

    [(_, _, _, _, consecutive_scans, status, _, _)] = discrepancies.upserts
    assert (consecutive_scans, status) == (2, DiscrepancyStatus.CONFIRMED)


async def test_a_stop_of_another_market_holds_nothing() -> None:
    use_case, discrepancies, _ = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("0"))],
        ledger=_held(),
        resting={(USER, POOL): ["SOLUSDT.P"]},
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1


async def test_a_stop_of_another_user_holds_nothing() -> None:
    other = uuid4()
    use_case, discrepancies, stops = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("0"))],
        ledger=_held(),
        resting={(other, POOL): [ALERT_SPELLING]},
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1
    assert stops.asked == [(USER, POOL)]


async def test_a_venue_that_still_holds_part_of_it_is_not_held() -> None:
    """Partly closed is not a fired stop: the stop closes the whole position. Whatever it
    is, it is a mismatch like any other."""
    use_case, discrepancies, _ = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("30"))],
        ledger=_held("76"),
        resting={(USER, POOL): [ALERT_SPELLING]},
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1


async def test_a_venue_position_the_ledger_does_not_hold_is_not_held() -> None:
    """The other direction: the venue holds a position no allocation owns. A resting stop for
    the market changes nothing about that."""
    use_case, discrepancies, _ = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("76"))],
        ledger=[],
        resting={(USER, POOL): [ALERT_SPELLING]},
    )

    await use_case.scan(uuid4())

    [(_, _, observation, _, _, _, _, _)] = discrepancies.upserts
    assert observation.kind is DiscrepancyKind.NO_MATCHING_ALLOCATION


async def test_agreeing_positions_never_ask_about_stops() -> None:
    use_case, discrepancies, stops = _build(
        venue=[VenuePosition(VENUE_SPELLING, Decimal("76"))],
        ledger=_held("76"),
        resting={(USER, POOL): [ALERT_SPELLING]},
    )

    await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert stops.asked == []


async def test_stops_are_asked_once_per_pool_however_many_markets_disagree() -> None:
    use_case, discrepancies, stops = _build(
        venue=[
            VenuePosition("DOGEUSDT", Decimal("0")),
            VenuePosition("SOLUSDT", Decimal("0")),
        ],
        ledger=[
            LedgerPosition("DOGEUSDT.P", (OpenAllocation(uuid4(), Decimal("76")),)),
            LedgerPosition("SOLUSDT.P", (OpenAllocation(uuid4(), Decimal("2")),)),
        ],
        resting={(USER, POOL): ["DOGEUSDT.P"]},
    )

    await use_case.scan(uuid4())

    # DOGE is held, SOL is not: only SOL opens.
    assert [row[1] for row in discrepancies.upserts] == ["SOLUSDT"]
    assert stops.asked == [(USER, POOL)]

"""``ScanPools`` — the reconciliation scan use case (design.md's component
inventory § reconciliation/application/scan_pools.py; design decisions
6-8; spec: reconciliation-scan).

Exercises the use case's orchestration of the domain's own pure rules
(``classify``, ``next_consecutive_scans``, ``derive_status``) against fakes,
plus the two deliberate asymmetries design.md calls out for this layer:
a per-pool VENUE read error is swallowed and the scan moves on to the next
pool, while anything else — a registry misconfiguration, a programming
error — propagates and kills the job so the queue retries it.

``DRY_RUN`` skip and successor-job enqueueing are NOT exercised here: both
belong to the Phase 5 job handler (design decision 11's own wording, "hard
skip INSIDE the handler"), mirroring how ``BalanceSyncHandler``/
``SweepHandler`` own the successor enqueue rather than ``SyncBalances``/
``ExpireReservations``.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from strategy_manager.reconciliation.application.ports import (
    DiscrepancyRecord,
    PoolKey,
    VenuePositionReadError,
)
from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.domain.positions import (
    LedgerPosition,
    OpenAllocation,
    VenuePosition,
)

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
POOL_A: PoolKey = ("bybit", "usdt-m", "USDT")
POOL_B: PoolKey = ("pionex", "spot", "USDT")


class FakeVenueReader:
    def __init__(
        self,
        positions: Sequence[VenuePosition] = (),
        raises: Exception | None = None,
    ) -> None:
        self._positions = list(positions)
        self._raises = raises
        self.calls = 0

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return list(self._positions)


class FakeVenueReaderRegistry:
    def __init__(self, readers: dict[tuple[str, str], FakeVenueReader]) -> None:
        self._readers = readers
        self.requested: list[tuple[str, str]] = []

    def for_pool(self, exchange: str, venue: str) -> FakeVenueReader:
        self.requested.append((exchange, venue))
        reader = self._readers.get((exchange, venue))
        if reader is None:
            raise LookupError(f"no venue reader registered for {exchange}/{venue}")
        return reader


class FakeLedgerPositions:
    def __init__(self, positions_by_pool: dict[PoolKey, list[LedgerPosition]]) -> None:
        self._positions_by_pool = positions_by_pool
        self.requested: list[PoolKey] = []

    async def net_positions_by_symbol(self, pool: PoolKey) -> list[LedgerPosition]:
        self.requested.append(pool)
        return list(self._positions_by_pool.get(pool, []))


class FakeDiscrepancyRepository:
    def __init__(
        self, open_by_pool: dict[PoolKey, list[DiscrepancyRecord]] | None = None
    ) -> None:
        self._open_by_pool = {k: list(v) for k, v in (open_by_pool or {}).items()}
        self.upserts: list[tuple] = []
        self.resolves: list[tuple] = []

    async def list_discrepancies(
        self,
        pool: PoolKey | None = None,
        status: DiscrepancyStatus | None = None,
        open_only: bool = False,
    ) -> list[DiscrepancyRecord]:
        del status  # unused by ScanPools; exercised only by future callers
        if pool is None:
            records: list[DiscrepancyRecord] = []
            for values in self._open_by_pool.values():
                records.extend(values)
            return records
        return list(self._open_by_pool.get(pool, []))

    async def upsert_open(
        self,
        pool: PoolKey,
        symbol: str,
        observation: Observation,
        open_allocation_ids: Sequence[UUID],
        consecutive_scans: int,
        status: DiscrepancyStatus,
        scan_id: UUID,
        at: datetime,
    ) -> None:
        self.upserts.append(
            (
                pool,
                symbol,
                observation,
                tuple(open_allocation_ids),
                consecutive_scans,
                status,
                scan_id,
                at,
            )
        )

    async def resolve_absent(
        self, pool: PoolKey, symbols: Sequence[str], scan_id: UUID, at: datetime
    ) -> int:
        self.resolves.append((pool, tuple(symbols), scan_id, at))
        return len(symbols)


class FrozenClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _record(
    pool: PoolKey,
    symbol: str,
    kind: DiscrepancyKind,
    venue_net_base: Decimal,
    ledger_net_base: Decimal,
    consecutive_scans: int = 1,
    status: DiscrepancyStatus = DiscrepancyStatus.OBSERVED,
) -> DiscrepancyRecord:
    exchange, venue, settlement_currency = pool
    return DiscrepancyRecord(
        id=uuid4(),
        exchange=exchange,
        venue=venue,
        settlement_currency=settlement_currency,
        symbol=symbol,
        kind=kind,
        venue_net_base=venue_net_base,
        ledger_net_base=ledger_net_base,
        open_allocation_ids=(),
        consecutive_scans=consecutive_scans,
        status=status,
        first_observed_at=NOW,
        last_observed_at=NOW,
        confirmed_at=None,
        resolved_at=None,
        first_scan_id=uuid4(),
        last_scan_id=uuid4(),
        resolved_by_scan_id=None,
    )


def _build(
    pools: Sequence[PoolKey],
    venue_readers: dict[tuple[str, str], FakeVenueReader],
    ledger_positions: dict[PoolKey, list[LedgerPosition]],
    open_discrepancies: dict[PoolKey, list[DiscrepancyRecord]] | None = None,
    confirmations_required: int = 2,
) -> tuple[
    ScanPools,
    FakeVenueReaderRegistry,
    FakeLedgerPositions,
    FakeDiscrepancyRepository,
    SpyCommit,
]:
    registry = FakeVenueReaderRegistry(venue_readers)
    ledger = FakeLedgerPositions(ledger_positions)
    discrepancies = FakeDiscrepancyRepository(open_discrepancies)
    commit = SpyCommit()
    use_case = ScanPools(
        pools=pools,
        venue_readers=registry,
        ledger_positions=ledger,
        discrepancies=discrepancies,
        clock=FrozenClock(NOW),
        commit=commit,
        confirmations_required=confirmations_required,
    )
    return use_case, registry, ledger, discrepancies, commit


# --- Agreement: no discrepancy at all ----------------------------------------


async def test_agreeing_positions_write_nothing() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("BTCUSDT", Decimal("1.5"))])
    ledger = {
        POOL_A: [
            LedgerPosition("BTCUSDT", (OpenAllocation(allocation_id, Decimal("1.5")),))
        ]
    }
    use_case, _, _, discrepancies, commit = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    result = await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert discrepancies.resolves == []
    assert result.discrepancies_opened == 0
    assert result.discrepancies_resolved == 0
    assert commit.commits == 1


# --- First observation of a new discrepancy ----------------------------------


async def test_a_fresh_disagreement_is_written_as_observed_with_count_one() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("BTCUSDT", Decimal("2.0"))])
    ledger = {
        POOL_A: [
            LedgerPosition("BTCUSDT", (OpenAllocation(allocation_id, Decimal("1.5")),))
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )
    scan_id = uuid4()

    result = await use_case.scan(scan_id)

    assert len(discrepancies.upserts) == 1
    (
        pool,
        symbol,
        observation,
        allocation_ids,
        consecutive_scans,
        status,
        written_scan_id,
        at,
    ) = discrepancies.upserts[0]
    assert pool == POOL_A
    assert symbol == "BTCUSDT"
    assert observation.kind is DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION
    assert observation.venue_net_base == Decimal("2.0")
    assert observation.ledger_net_base == Decimal("1.5")
    assert allocation_ids == (allocation_id,)
    assert consecutive_scans == 1
    assert status is DiscrepancyStatus.OBSERVED
    assert written_scan_id == scan_id
    assert at == NOW
    assert result.discrepancies_opened == 1


# --- Repeated identical observation confirms ---------------------------------


async def test_the_same_disagreement_twice_confirms_at_the_threshold() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("BTCUSDT", Decimal("2.0"))])
    ledger = {
        POOL_A: [
            LedgerPosition("BTCUSDT", (OpenAllocation(allocation_id, Decimal("1.5")),))
        ]
    }
    prior = _record(
        POOL_A,
        "BTCUSDT",
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        Decimal("2.0"),
        Decimal("1.5"),
        consecutive_scans=1,
        status=DiscrepancyStatus.OBSERVED,
    )
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        ledger,
        open_discrepancies={POOL_A: [prior]},
        confirmations_required=2,
    )

    await use_case.scan(uuid4())

    _, _, _, _, consecutive_scans, status, _, _ = discrepancies.upserts[0]
    assert consecutive_scans == 2
    assert status is DiscrepancyStatus.CONFIRMED


async def test_a_changed_observation_resets_the_count() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("BTCUSDT", Decimal("3.0"))])
    ledger = {
        POOL_A: [
            LedgerPosition("BTCUSDT", (OpenAllocation(allocation_id, Decimal("1.5")),))
        ]
    }
    prior = _record(
        POOL_A,
        "BTCUSDT",
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        Decimal("2.0"),
        Decimal("1.5"),
        consecutive_scans=5,
        status=DiscrepancyStatus.CONFIRMED,
    )
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        ledger,
        open_discrepancies={POOL_A: [prior]},
    )

    await use_case.scan(uuid4())

    _, _, _, _, consecutive_scans, status, _, _ = discrepancies.upserts[0]
    assert consecutive_scans == 1
    assert status is DiscrepancyStatus.OBSERVED


# --- Automatic resolution -----------------------------------------------------


async def test_a_symbol_now_in_agreement_resolves_its_open_row() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("BTCUSDT", Decimal("1.5"))])
    ledger = {
        POOL_A: [
            LedgerPosition("BTCUSDT", (OpenAllocation(allocation_id, Decimal("1.5")),))
        ]
    }
    prior = _record(
        POOL_A,
        "BTCUSDT",
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        Decimal("2.0"),
        Decimal("1.5"),
    )
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        ledger,
        open_discrepancies={POOL_A: [prior]},
    )
    scan_id = uuid4()

    result = await use_case.scan(scan_id)

    assert discrepancies.upserts == []
    assert len(discrepancies.resolves) == 1
    pool, symbols, written_scan_id, at = discrepancies.resolves[0]
    assert pool == POOL_A
    assert symbols == ("BTCUSDT",)
    assert written_scan_id == scan_id
    assert at == NOW
    assert result.discrepancies_resolved == 1


async def test_a_symbol_vanished_from_both_sides_still_resolves() -> None:
    """The previously-discrepant symbol is reported by neither the venue nor
    the ledger this time. Both sides are treated as flat, which is
    agreement, and the open row must resolve rather than sit forever."""
    prior = _record(
        POOL_A,
        "ETHUSDT",
        DiscrepancyKind.NO_MATCHING_ALLOCATION,
        Decimal("1.0"),
        Decimal("0"),
    )
    venue_reader = FakeVenueReader([])
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        {POOL_A: []},
        open_discrepancies={POOL_A: [prior]},
    )

    result = await use_case.scan(uuid4())

    assert len(discrepancies.resolves) == 1
    assert discrepancies.resolves[0][1] == ("ETHUSDT",)
    assert result.discrepancies_resolved == 1


# --- Design decision 8: per-pool venue errors are swallowed, others are not --


async def test_a_venue_read_error_is_swallowed_and_the_scan_continues() -> None:
    failing = FakeVenueReader(raises=VenuePositionReadError("bybit unreachable"))
    healthy_allocation = uuid4()
    healthy_reader = FakeVenueReader([VenuePosition("BTCUSDT", Decimal("2.0"))])
    ledger = {
        POOL_B: [
            LedgerPosition(
                "BTCUSDT", (OpenAllocation(healthy_allocation, Decimal("1.5")),)
            )
        ]
    }
    use_case, registry, _, discrepancies, commit = _build(
        [POOL_A, POOL_B],
        {("bybit", "usdt-m"): failing, ("pionex", "spot"): healthy_reader},
        ledger,
    )

    result = await use_case.scan(uuid4())

    assert result.pools_skipped == 1
    assert result.pools_scanned == 1
    # the failing pool wrote nothing, the healthy one still did its work
    assert len(discrepancies.upserts) == 1
    assert discrepancies.upserts[0][0] == POOL_B
    # both pools were still attempted
    assert set(registry.requested) == {("bybit", "usdt-m"), ("pionex", "spot")}
    assert commit.commits == 1


async def test_a_non_venue_error_propagates_and_is_not_swallowed() -> None:
    """Only ``VenuePositionReadError`` is a venue error. Anything else —
    here, a registry lookup failure for an unregistered pool — is a
    configuration/programming error and must be loud."""
    use_case, _, _, discrepancies, commit = _build(
        [POOL_A],
        {},  # no reader registered for POOL_A at all
        {},
    )

    with pytest.raises(LookupError):
        await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert commit.commits == 0


async def test_a_programming_error_from_the_venue_reader_also_propagates() -> None:
    failing = FakeVenueReader(raises=RuntimeError("boom"))
    use_case, _, _, _, commit = _build([POOL_A], {("bybit", "usdt-m"): failing}, {})

    with pytest.raises(RuntimeError, match="boom"):
        await use_case.scan(uuid4())

    assert commit.commits == 0


# --- Every configured pool is attempted, once, with the right key -----------


async def test_every_configured_pool_is_read_from_the_venue_and_the_ledger() -> None:
    venue_reader_a = FakeVenueReader([])
    venue_reader_b = FakeVenueReader([])
    use_case, registry, ledger, _, _ = _build(
        [POOL_A, POOL_B],
        {("bybit", "usdt-m"): venue_reader_a, ("pionex", "spot"): venue_reader_b},
        {},
    )

    await use_case.scan(uuid4())

    assert venue_reader_a.calls == 1
    assert venue_reader_b.calls == 1
    assert ledger.requested == [POOL_A, POOL_B]


# --- Spelling: the ledger stores TradingView's form, the venue its own ------
#
# The ledger records the SIGNAL's symbol (``STXUSDT.P``, TradingView's
# perpetual form) while Bybit and Binance report the market by their own name
# (``STXUSDT``). Every test below uses a DIFFERENT spelling on each side on
# purpose: the reconciliation tests that shipped used the same one on both, and
# that is exactly how two false discrepancies per open position went unseen.


async def test_one_market_spelled_differently_on_each_side_is_agreement() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.5"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_id, Decimal("0.5")),))
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    result = await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert discrepancies.resolves == []
    assert result.discrepancies_opened == 0


async def test_a_real_mismatch_across_spellings_is_one_row_under_the_market_key() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.3"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_id, Decimal("0.5")),))
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1
    _, symbol, observation, allocation_ids, _, _, _, _ = discrepancies.upserts[0]
    assert symbol == "STXUSDT"
    assert observation.kind is DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION
    assert observation.venue_net_base == Decimal("0.3")
    assert observation.ledger_net_base == Decimal("0.5")
    assert allocation_ids == (allocation_id,)


async def test_two_ledger_spellings_of_one_market_merge_into_one_comparison() -> None:
    """``STXUSDT.P`` and ``STXUSDT`` in the ledger are one market. Merged,
    allocation A's two halves are ONE open allocation, and the market's net
    is the sum of both spellings -- overwriting one with the other would lose
    part of the position."""
    allocation_a, allocation_b = uuid4(), uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.9"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_a, Decimal("0.2")),)),
            LedgerPosition(
                "STXUSDT",
                (
                    OpenAllocation(allocation_a, Decimal("0.1")),
                    OpenAllocation(allocation_b, Decimal("0.2")),
                ),
            ),
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1
    _, symbol, observation, allocation_ids, _, _, _, _ = discrepancies.upserts[0]
    assert symbol == "STXUSDT"
    assert observation.ledger_net_base == Decimal("0.5")
    # Allocation A appears once, not once per spelling.
    assert allocation_ids == (allocation_a, allocation_b)
    assert observation.kind is DiscrepancyKind.AMBIGUOUS_PARTIAL_REDUCE


async def test_an_allocation_opened_and_closed_under_two_spellings_is_closed() -> None:
    """Opened as ``STXUSDT.P`` (+0.5), closed as ``STXUSDT`` (-0.5). The
    projection groups per spelling, so each half survives its ``HAVING net !=
    0`` alone and the allocation comes back twice. Merged, it nets to zero and
    is closed -- so the venue's +0.3 has NO allocation behind it.

    Kept at zero instead, it would still count as an open allocation, skip
    rung 1 of the ladder and read ``ATTRIBUTABLE_SINGLE_ALLOCATION``: blaming a
    position on an allocation that is already closed."""
    allocation_a = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.3"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_a, Decimal("0.5")),)),
            LedgerPosition("STXUSDT", (OpenAllocation(allocation_a, Decimal("-0.5")),)),
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1
    _, symbol, observation, allocation_ids, _, _, _, _ = discrepancies.upserts[0]
    assert symbol == "STXUSDT"
    assert observation.kind is DiscrepancyKind.NO_MATCHING_ALLOCATION
    assert allocation_ids == ()


async def test_an_allocation_closed_across_spellings_agrees_with_a_flat_venue() -> None:
    """The same closed allocation against a flat venue is agreement, not a
    discrepancy: both sides say nothing is held."""
    allocation_a = uuid4()
    venue_reader = FakeVenueReader([])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_a, Decimal("0.5")),)),
            LedgerPosition("STXUSDT", (OpenAllocation(allocation_a, Decimal("-0.5")),)),
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert discrepancies.upserts == []


async def test_one_allocation_split_across_two_spellings_is_still_one_allocation() -> None:
    """Summed per allocation, a single allocation recorded under both
    spellings stays attributable to that one allocation."""
    allocation_a = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.2"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_a, Decimal("0.2")),)),
            LedgerPosition("STXUSDT", (OpenAllocation(allocation_a, Decimal("0.1")),)),
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1
    _, _, observation, allocation_ids, _, _, _, _ = discrepancies.upserts[0]
    assert allocation_ids == (allocation_a,)
    assert observation.ledger_net_base == Decimal("0.3")
    assert observation.kind is DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION


async def test_two_merged_ledger_spellings_that_match_the_venue_are_agreement() -> None:
    allocation_a = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.3"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_a, Decimal("0.2")),)),
            LedgerPosition("STXUSDT", (OpenAllocation(allocation_a, Decimal("0.1")),)),
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert discrepancies.upserts == []


async def test_a_previous_row_resolves_once_the_spellings_agree() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.5"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_id, Decimal("0.5")),))
        ]
    }
    prior = _record(
        POOL_A,
        "STXUSDT",
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        Decimal("0.3"),
        Decimal("0.5"),
    )
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        ledger,
        open_discrepancies={POOL_A: [prior]},
    )

    result = await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert len(discrepancies.resolves) == 1
    assert discrepancies.resolves[0][1] == ("STXUSDT",)
    assert result.discrepancies_resolved == 1


async def test_a_previous_row_stored_under_the_marker_spelling_still_resolves() -> None:
    """A row written before this fix carries whichever spelling that scan saw.
    Resolving must name the spelling the row is STORED under, or the
    repository's ``symbol IN (...)`` matches nothing and it stays open."""
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.5"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_id, Decimal("0.5")),))
        ]
    }
    prior = _record(
        POOL_A,
        "STXUSDT.P",
        DiscrepancyKind.ATTRIBUTABLE_FULL_CLOSE,
        Decimal("0"),
        Decimal("0.5"),
    )
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        ledger,
        open_discrepancies={POOL_A: [prior]},
    )

    await use_case.scan(uuid4())

    assert discrepancies.upserts == []
    assert len(discrepancies.resolves) == 1
    assert discrepancies.resolves[0][1] == ("STXUSDT.P",)


async def test_a_still_open_marker_spelled_row_carries_its_count_and_is_superseded() -> None:
    """The disagreement persists, so it is written under the market key -- and
    the row under the old spelling must not stay open beside it as a second
    record of one market. Its count carries over: the observation is the same."""
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("STXUSDT", Decimal("0.3"))])
    ledger = {
        POOL_A: [
            LedgerPosition("STXUSDT.P", (OpenAllocation(allocation_id, Decimal("0.5")),))
        ]
    }
    prior = _record(
        POOL_A,
        "STXUSDT.P",
        DiscrepancyKind.ATTRIBUTABLE_SINGLE_ALLOCATION,
        Decimal("0.3"),
        Decimal("0.5"),
        consecutive_scans=1,
    )
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A],
        {("bybit", "usdt-m"): venue_reader},
        ledger,
        open_discrepancies={POOL_A: [prior]},
        confirmations_required=2,
    )

    await use_case.scan(uuid4())

    assert len(discrepancies.upserts) == 1
    _, symbol, _, _, consecutive_scans, status, _, _ = discrepancies.upserts[0]
    assert symbol == "STXUSDT"
    assert consecutive_scans == 2
    assert status is DiscrepancyStatus.CONFIRMED
    assert len(discrepancies.resolves) == 1
    assert discrepancies.resolves[0][1] == ("STXUSDT.P",)


async def test_a_pionex_perp_suffix_and_lowercase_map_to_the_same_market() -> None:
    allocation_id = uuid4()
    venue_reader = FakeVenueReader([VenuePosition("btc_usdt", Decimal("1.0"))])
    ledger = {
        POOL_A: [
            LedgerPosition(
                "BTC_USDT_PERP", (OpenAllocation(allocation_id, Decimal("1.0")),)
            )
        ]
    }
    use_case, _, _, discrepancies, _ = _build(
        [POOL_A], {("bybit", "usdt-m"): venue_reader}, ledger
    )

    await use_case.scan(uuid4())

    assert discrepancies.upserts == []

"""``ScanPools``: the reconciliation scan (design.md's component inventory
§ reconciliation/application/scan_pools.py; design decisions 6-8; spec:
reconciliation-scan).

Iterates every configured pool, compares the venue's live-reported net
position against the ledger's projected one per symbol, and lands the
verdict through ``DiscrepancyRepositoryPort``. Comparison and status
derivation are the domain's own pure rules (``classify``,
``next_consecutive_scans``, ``derive_status``) — this use case only reads
the previous state, calls them, and persists the result. It never writes to
``ledger_entries`` or ``execution_attempts``, and never touches
``CapitalPool.available`` (spec's write-boundary requirement): the only
writes here are discrepancy rows.

**Design decision 8's asymmetry lives HERE, in the per-pool loop, not in a
caller.** A ``VenuePositionReadError`` from one pool's live venue call is
caught, logged, and the scan moves on to the next pool — deliberately
UNLIKE ``CompositeBalanceSync``, which lets one exchange's failure fail the
whole job. The queue has no backoff and ``max_attempts`` kills a job chain
outright; ``balance.sync`` dying is loud (a stale snapshot halts trading),
but a dead reconciliation chain is silent, so this loop refuses to let one
bad venue read take every other pool down with it. Anything OTHER than
``VenuePositionReadError`` — a registry lookup failure for an unserved
pool, a programming error — is NOT caught here and propagates, exactly like
``VenueExchangeRegistry.for_pool`` already behaves on the execution side.

**What this use case deliberately does NOT do**: check ``DRY_RUN`` or decide
whether to enqueue a successor job. Design decision 11 states the DRY_RUN
skip happens "INSIDE the handler", and the successor enqueue is the job
handler's job everywhere else in this codebase (``SweepHandler``,
``BalanceSyncHandler`` own it; ``ExpireReservations``/``SyncBalances`` do
not). The Phase 5 ``ReconciliationScanHandler`` owns both, wrapping
``ScanPools`` the same way those handlers wrap their use case.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from strategy_manager.reconciliation.application.market_key import market_key
from strategy_manager.reconciliation.application.ports import (
    CommitPort,
    DiscrepancyRecord,
    DiscrepancyRepositoryPort,
    LedgerSymbolPositionPort,
    PoolKey,
    VenuePositionReaderRegistryPort,
    VenuePositionReadError,
)
from strategy_manager.reconciliation.domain.classify import classify
from strategy_manager.reconciliation.domain.discrepancy import (
    Observation,
    derive_status,
    next_consecutive_scans,
)
from strategy_manager.reconciliation.domain.positions import (
    LedgerPosition,
    OpenAllocation,
    VenuePosition,
)
from strategy_manager.shared.application.ports import ClockPort

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ScanResult:
    pools_scanned: int
    pools_skipped: int
    discrepancies_opened: int
    discrepancies_resolved: int


class ScanPools:
    def __init__(
        self,
        pools: Sequence[PoolKey],
        venue_readers: VenuePositionReaderRegistryPort,
        ledger_positions: LedgerSymbolPositionPort,
        discrepancies: DiscrepancyRepositoryPort,
        clock: ClockPort,
        commit: CommitPort,
        confirmations_required: int,
    ) -> None:
        self._pools = pools
        self._venue_readers = venue_readers
        self._ledger_positions = ledger_positions
        self._discrepancies = discrepancies
        self._clock = clock
        self._commit = commit
        self._confirmations_required = confirmations_required

    async def scan(self, scan_id: UUID) -> ScanResult:
        """One pass over every configured pool.

        ``scan_id`` is the caller's own job id (a ``jobs.id`` value), landed
        verbatim in ``first_scan_id``/``last_scan_id``/``resolved_by_scan_id``
        — this use case never mints its own identifier for the scan.
        """
        at = self._clock.now()
        pools_skipped = 0
        opened = 0
        resolved = 0

        for pool in self._pools:
            exchange, venue, settlement_currency = pool
            try:
                venue_positions = await self._venue_readers.for_pool(
                    exchange, venue
                ).open_positions(pool)
            except VenuePositionReadError as exc:
                logger.warning(
                    "reconciliation scan: venue read failed for %s/%s/%s, "
                    "skipping this pool this scan: %s",
                    exchange,
                    venue,
                    settlement_currency,
                    exc,
                )
                pools_skipped += 1
                continue

            ledger_positions = await self._ledger_positions.net_positions_by_symbol(pool)
            previous = await self._discrepancies.list_discrepancies(
                pool=pool, open_only=True
            )

            pool_opened, pool_resolved = await self._scan_pool(
                pool, venue_positions, ledger_positions, previous, scan_id, at
            )
            opened += pool_opened
            resolved += pool_resolved

        await self._commit.commit()
        return ScanResult(
            pools_scanned=len(self._pools) - pools_skipped,
            pools_skipped=pools_skipped,
            discrepancies_opened=opened,
            discrepancies_resolved=resolved,
        )

    async def _scan_pool(
        self,
        pool: PoolKey,
        venue_positions: Sequence[VenuePosition],
        ledger_positions: Sequence[LedgerPosition],
        previous: Sequence[DiscrepancyRecord],
        scan_id: UUID,
        at: datetime,
    ) -> tuple[int, int]:
        """Compares one pool's positions symbol by symbol.

        The comparison universe is the union of every symbol seen on
        either side THIS scan, plus every symbol with a still-open row from
        a PREVIOUS scan — the last part is what lets a symbol that vanished
        from both the venue and the ledger still resolve (spec's automatic
        resolution requirement), rather than being silently skipped because
        neither side mentions it any more.
        """
        # Every side is keyed by ``market_key``, never by the raw symbol: the
        # ledger holds TradingView's spelling (``STXUSDT.P``) and the venue its
        # own (``STXUSDT``). Keyed raw, one open position is two false
        # discrepancies -- and the ledger-side one reads as a full close of a
        # position that is still open.
        venue_by_symbol = _venue_by_market(venue_positions)
        ledger_by_symbol = _ledger_by_market(ledger_positions)
        previous_by_symbol = _previous_by_market(previous)

        # Sorted, not a bare set: this loop writes one row per symbol, and two
        # scans touching the same pool in an unpredictable order is how
        # lock-ordering deadlocks are born. A stable order also keeps the
        # tests deterministic.
        symbols = sorted(
            set(venue_by_symbol) | set(ledger_by_symbol) | set(previous_by_symbol)
        )

        opened = 0
        # Resolution names the spelling a row is STORED under, because the
        # repository matches ``symbol IN (...)`` literally. A row written before
        # keys were canonical may carry a marker spelling.
        resolved_symbols: list[str] = []

        for symbol in symbols:
            venue_position = venue_by_symbol.get(symbol) or VenuePosition(symbol, _ZERO)
            ledger_position = ledger_by_symbol.get(symbol) or LedgerPosition(symbol, ())
            prior_records = previous_by_symbol.get(symbol, ())

            kind = classify(venue_position, ledger_position)
            if kind is None:
                resolved_symbols.extend(record.symbol for record in prior_records)
                continue

            # The row stores the MARKET KEY, not either side's spelling: it
            # describes a disagreement about one market, and the two spellings
            # of it are an artefact of who reported it. Storing one side's
            # spelling would also make the row's identity (the partial unique
            # index on pool + symbol) depend on which side happened to report.
            # Any still-open row under another spelling of this market is
            # superseded by this one, and resolved rather than left open as a
            # second record of the same market.
            resolved_symbols.extend(
                record.symbol for record in prior_records if record.symbol != symbol
            )

            observation = Observation(
                kind=kind,
                venue_net_base=venue_position.net_base,
                ledger_net_base=ledger_position.net_base,
            )
            prior_record = _prior_record(symbol, prior_records)
            if prior_record is None:
                consecutive_scans = 1
            else:
                prior_observation = Observation(
                    kind=prior_record.kind,
                    venue_net_base=prior_record.venue_net_base,
                    ledger_net_base=prior_record.ledger_net_base,
                )
                consecutive_scans = next_consecutive_scans(
                    prior_observation, observation, prior_record.consecutive_scans
                )
            status = derive_status(consecutive_scans, self._confirmations_required)

            await self._discrepancies.upsert_open(
                pool,
                symbol,
                observation,
                ledger_position.allocation_ids,
                consecutive_scans,
                status,
                scan_id,
                at,
            )
            opened += 1

        resolved = 0
        if resolved_symbols:
            resolved = await self._discrepancies.resolve_absent(
                pool, resolved_symbols, scan_id, at
            )

        return opened, resolved


def _venue_by_market(positions: Sequence[VenuePosition]) -> dict[str, VenuePosition]:
    """One ``VenuePosition`` per market key.

    A venue reports each market once under its own name, so a collision
    should not happen; if it ever does, the nets are summed rather than one
    silently overwriting the other.
    """
    net_by_market: dict[str, Decimal] = {}
    for position in positions:
        key = market_key(position.symbol)
        net_by_market[key] = net_by_market.get(key, _ZERO) + position.net_base
    return {key: VenuePosition(key, net) for key, net in net_by_market.items()}


def _ledger_by_market(positions: Sequence[LedgerPosition]) -> dict[str, LedgerPosition]:
    """One ``LedgerPosition`` per market key, merging every spelling.

    The ledger can hold one market under two spellings (``STXUSDT.P`` from a
    signal, ``STXUSDT`` from elsewhere), and ``net_positions_by_symbol``
    returns one ``LedgerPosition`` per spelling. Overwriting one with the other
    would drop part of the position. They are merged instead, and an
    allocation appearing under both spellings becomes ONE ``OpenAllocation``
    whose ``net_base`` is the sum of both -- counted twice, it would turn a
    single attributable allocation into a spurious ambiguous one.

    An allocation whose MERGED net is zero is dropped, because that is exactly
    what the projection itself would have decided had it grouped by market
    rather than by spelling. ``net_positions_by_symbol`` keeps an allocation
    only ``HAVING net != 0``, but it groups per spelling -- so an allocation
    opened as ``STXUSDT.P`` and closed as ``STXUSDT`` comes back twice, at
    +0.5 and -0.5, each half passing that filter on its own. Merged, it is
    closed. Keeping it would leave a closed allocation on the books and steer
    the ladder away from rung 1: a venue position with no real allocation
    behind it would read ``ATTRIBUTABLE_SINGLE_ALLOCATION`` instead of
    ``NO_MATCHING_ALLOCATION``.
    """
    net_by_allocation: dict[str, dict[UUID, Decimal]] = {}
    for position in positions:
        allocations = net_by_allocation.setdefault(market_key(position.symbol), {})
        for allocation in position.open_allocations:
            allocations[allocation.allocation_id] = (
                allocations.get(allocation.allocation_id, _ZERO) + allocation.net_base
            )
    return {
        key: LedgerPosition(
            key,
            tuple(
                OpenAllocation(allocation_id, net)
                for allocation_id, net in allocations.items()
                if net != _ZERO
            ),
        )
        for key, allocations in net_by_allocation.items()
    }


def _previous_by_market(
    previous: Sequence[DiscrepancyRecord],
) -> dict[str, tuple[DiscrepancyRecord, ...]]:
    """Open rows grouped by market key.

    More than one row per key is possible only for rows written before keys
    were canonical, when each spelling got a row of its own.
    """
    grouped: dict[str, list[DiscrepancyRecord]] = {}
    for record in previous:
        grouped.setdefault(market_key(record.symbol), []).append(record)
    return {key: tuple(records) for key, records in grouped.items()}


def _prior_record(
    symbol: str, records: Sequence[DiscrepancyRecord]
) -> DiscrepancyRecord | None:
    """The row whose count this observation continues: the one already
    stored under the market key if there is one, else the one under another
    spelling of it, since both described the same market."""
    for record in records:
        if record.symbol == symbol:
            return record
    return records[0] if records else None

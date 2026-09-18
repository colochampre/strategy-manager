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
from strategy_manager.reconciliation.domain.positions import LedgerPosition, VenuePosition
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
        venue_by_symbol = {position.symbol: position for position in venue_positions}
        ledger_by_symbol = {position.symbol: position for position in ledger_positions}
        previous_by_symbol = {record.symbol: record for record in previous}

        # Sorted, not a bare set: this loop writes one row per symbol, and two
        # scans touching the same pool in an unpredictable order is how
        # lock-ordering deadlocks are born. A stable order also keeps the
        # tests deterministic.
        symbols = sorted(
            set(venue_by_symbol) | set(ledger_by_symbol) | set(previous_by_symbol)
        )

        opened = 0
        resolved_symbols: list[str] = []

        for symbol in symbols:
            venue_position = venue_by_symbol.get(symbol) or VenuePosition(symbol, _ZERO)
            ledger_position = ledger_by_symbol.get(symbol) or LedgerPosition(symbol, ())

            kind = classify(venue_position, ledger_position)
            if kind is None:
                if symbol in previous_by_symbol:
                    resolved_symbols.append(symbol)
                continue

            observation = Observation(
                kind=kind,
                venue_net_base=venue_position.net_base,
                ledger_net_base=ledger_position.net_base,
            )
            prior_record = previous_by_symbol.get(symbol)
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

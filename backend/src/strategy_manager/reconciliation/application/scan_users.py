"""``ScanUsers``: one reconciliation scan over every user's own pools
(multi-user design AD10, tasks.md B.8).

A venue's net position is an account's, and an account is a user's: the same
market held by two users is two accounts, two ledgers and two discrepancies.
Each user therefore gets a ``ScanPools`` of their own, built by the caller
with THAT user's venue reader (their key) and THAT user's pools, and this
class runs them one after the other and adds their results up.

It is deliberately thin. All the scan's rules (classification, consecutive
scans, per-pool tolerance of a failed venue read) stay in ``ScanPools``; the
only thing added here is that one user's scan cannot be skipped because of
another's. A ``VenuePositionReadError`` never reaches this level (``ScanPools``
swallows it per pool); anything else is a configuration or programming error
and propagates, killing the job exactly as it does for a single ``ScanPools``.

It satisfies ``ScanPoolsPort`` (the handler's view of a scan), so the handler,
its DRY_RUN skip and its single successor enqueue per job are unchanged.
"""

from collections.abc import Sequence
from uuid import UUID

from strategy_manager.reconciliation.application.reconciliation_scan_handler import (
    ScanPoolsPort,
)
from strategy_manager.reconciliation.application.scan_pools import ScanResult


class ScanUsers:
    def __init__(self, scans: Sequence[ScanPoolsPort]) -> None:
        """``scans``: one ``ScanPools`` per user, in the order they run."""
        self._scans = scans

    async def scan(self, scan_id: UUID) -> ScanResult:
        scanned = skipped = opened = resolved = 0
        for scan in self._scans:
            result = await scan.scan(scan_id)
            scanned += result.pools_scanned
            skipped += result.pools_skipped
            opened += result.discrepancies_opened
            resolved += result.discrepancies_resolved
        return ScanResult(
            pools_scanned=scanned,
            pools_skipped=skipped,
            discrepancies_opened=opened,
            discrepancies_resolved=resolved,
        )

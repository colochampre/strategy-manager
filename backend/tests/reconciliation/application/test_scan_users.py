"""``ScanUsers``: reconciliation runs per user's pool, with that user's own
venue read (multi-user design AD10, tasks.md B.8).

Two users hold the SAME market. The venue's net position is an account's, so
each is read with their own reader and each gets their own discrepancy; the
old single-holder arrangement could scan only one of them.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.reconciliation.application.ports import (
    PoolKey,
    VenuePositionReadError,
)
from strategy_manager.reconciliation.application.scan_pools import ScanPools
from strategy_manager.reconciliation.application.scan_users import ScanUsers
from strategy_manager.reconciliation.domain.discrepancy import (
    DiscrepancyKind,
    DiscrepancyStatus,
    Observation,
)
from strategy_manager.reconciliation.domain.positions import LedgerPosition, VenuePosition

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
MARKET: PoolKey = ("bybit", "usdt-m", "USDT")
ALICE = UUID("a11ce000-0000-4000-8000-000000000001")
BOB = UUID("b0b00000-0000-4000-8000-000000000002")


class _UserReader:
    """The venue read of ONE user's account; remembers it was used."""

    def __init__(self, owner: UUID, positions: Sequence[VenuePosition], raises: bool = False):
        self.owner = owner
        self._positions = list(positions)
        self._raises = raises
        self.calls = 0

    async def open_positions(self, pool: PoolKey) -> list[VenuePosition]:
        self.calls += 1
        if self._raises:
            raise VenuePositionReadError(f"venue unreachable for {self.owner}")
        return list(self._positions)


class _Registry:
    def __init__(self, reader: _UserReader) -> None:
        self._reader = reader

    def for_pool(self, exchange: str, venue: str) -> _UserReader:
        return self._reader


class _Ledger:
    """Each user's ledger holds nothing, so any venue position is a disagreement."""

    def __init__(self) -> None:
        self.users: list[UUID] = []

    async def net_positions_by_symbol(self, user_id: UUID, pool: PoolKey) -> list[LedgerPosition]:
        self.users.append(user_id)
        return []


class _Discrepancies:
    def __init__(self) -> None:
        self.upserts: list[tuple[UUID, PoolKey, str, Decimal]] = []

    async def list_discrepancies(self, **kwargs: object) -> list[object]:
        return []

    async def upsert_open(
        self,
        user_id: UUID,
        pool: PoolKey,
        symbol: str,
        observation: Observation,
        open_allocation_ids: Sequence[UUID],
        consecutive_scans: int,
        status: DiscrepancyStatus,
        scan_id: UUID,
        at: datetime,
    ) -> None:
        assert observation.kind is DiscrepancyKind.NO_MATCHING_ALLOCATION
        self.upserts.append((user_id, pool, symbol, observation.venue_net_base))

    async def resolve_absent(
        self, user_id: UUID, pool: PoolKey, symbols: Sequence[str], scan_id: UUID, at: datetime
    ) -> int:
        return 0


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Commit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _scan_of(
    user: UUID, reader: _UserReader, ledger: _Ledger, discrepancies: _Discrepancies
) -> ScanPools:
    return ScanPools(
        pools=[MARKET],
        pool_users={MARKET: user},
        venue_readers=_Registry(reader),  # type: ignore[arg-type]
        ledger_positions=ledger,
        discrepancies=discrepancies,  # type: ignore[arg-type]
        clock=_Clock(),
        commit=_Commit(),
        confirmations_required=2,
    )


async def test_two_users_on_one_market_are_each_read_with_their_own_reader() -> None:
    alice_reader = _UserReader(ALICE, [VenuePosition("BTCUSDT", Decimal("1.0"))])
    bob_reader = _UserReader(BOB, [VenuePosition("BTCUSDT", Decimal("3.0"))])
    ledger = _Ledger()
    discrepancies = _Discrepancies()
    scan = ScanUsers(
        [
            _scan_of(ALICE, alice_reader, ledger, discrepancies),
            _scan_of(BOB, bob_reader, ledger, discrepancies),
        ]
    )

    result = await scan.scan(uuid4())

    assert (alice_reader.calls, bob_reader.calls) == (1, 1)
    assert ledger.users == [ALICE, BOB]
    # Each user's own discrepancy, carrying that user's own venue net.
    assert discrepancies.upserts == [
        (ALICE, MARKET, "BTCUSDT", Decimal("1.0")),
        (BOB, MARKET, "BTCUSDT", Decimal("3.0")),
    ]
    assert result.pools_scanned == 2
    assert result.discrepancies_opened == 2


async def test_one_users_failed_venue_read_does_not_stop_the_other_users_scan() -> None:
    alice_reader = _UserReader(ALICE, [], raises=True)
    bob_reader = _UserReader(BOB, [VenuePosition("ETHUSDT", Decimal("2.0"))])
    ledger = _Ledger()
    discrepancies = _Discrepancies()
    scan = ScanUsers(
        [
            _scan_of(ALICE, alice_reader, ledger, discrepancies),
            _scan_of(BOB, bob_reader, ledger, discrepancies),
        ]
    )

    result = await scan.scan(uuid4())

    assert discrepancies.upserts == [(BOB, MARKET, "ETHUSDT", Decimal("2.0"))]
    assert (result.pools_scanned, result.pools_skipped) == (1, 1)
    assert result.discrepancies_opened == 1

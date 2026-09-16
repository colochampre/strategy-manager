"""``SyncBalances`` — the only use case allowed to make a remote balance call.

What matters most here is the failure path. Writing anything at all on a
failed read would refresh ``observed_at`` and reset the staleness clock,
turning an exchange outage into a snapshot that looks perfectly healthy.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.accounts.application.sync_balances import SyncBalances
from strategy_manager.shared.domain.money import Exchange

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
POOLS: list[PoolKey] = [("spot", "USDT"), ("usdt-m", "USDT")]


def _reading(venue: str, available: str) -> PoolBalanceReading:
    return PoolBalanceReading(
        exchange=Exchange.BYBIT,
        venue=venue,
        settlement_currency="USDT",
        total=Decimal(available),
        available=Decimal(available),
        observed_at=NOW,
    )


class StubReader:
    def __init__(
        self,
        readings: list[PoolBalanceReading] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._readings = readings or []
        self._raises = raises
        self.requested: list[Sequence[PoolKey]] = []

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        self.requested.append(pools)
        if self._raises is not None:
            raise self._raises
        return self._readings


class SpyWriter:
    def __init__(self) -> None:
        self.written: list[Sequence[PoolBalanceReading]] = []

    async def upsert(self, readings: Sequence[PoolBalanceReading]) -> None:
        self.written.append(readings)


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _build(reader: StubReader) -> tuple[SyncBalances, SpyWriter, SpyCommit]:
    writer = SpyWriter()
    commit = SpyCommit()
    sync = SyncBalances(
        pools=POOLS,
        reader=reader,
        snapshots=writer,
        commit=commit,
    )
    return sync, writer, commit


async def test_every_configured_pool_is_requested_from_the_exchange() -> None:
    reader = StubReader([_reading("spot", "1")])
    sync, _, _ = _build(reader)

    await sync.sync()

    assert list(reader.requested[0]) == POOLS


async def test_the_readings_are_written_and_committed() -> None:
    readings = [_reading("spot", "600.5"), _reading("usdt-m", "0")]
    sync, writer, commit = _build(StubReader(readings))

    result = await sync.sync()

    assert list(writer.written[0]) == readings
    assert commit.commits == 1
    assert result.synced == 2


async def test_a_failed_read_writes_nothing_and_commits_nothing() -> None:
    """The previous snapshot must stay untouched so it keeps ageing and
    eventually blocks allocation. A rewrite would hide the outage."""
    sync, writer, commit = _build(StubReader(raises=RuntimeError("pionex down")))

    with pytest.raises(RuntimeError):
        await sync.sync()

    assert writer.written == []
    assert commit.commits == 0

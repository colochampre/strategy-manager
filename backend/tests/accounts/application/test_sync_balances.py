"""``SyncBalances`` — the only use case allowed to make a remote balance call.

What matters most here is the failure path. Writing anything at all on a
failed read would refresh ``observed_at`` and reset the staleness clock,
turning an exchange outage into a snapshot that looks perfectly healthy.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.accounts.application.sync_balances import (
    CompositeBalanceSync,
    SyncBalances,
    SyncResult,
)
from strategy_manager.shared.domain.money import Exchange
from tests.owner import OWNER_ID

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)
POOLS: list[PoolKey] = [("pionex", "spot", "USDT"), ("bybit", "usdt-m", "USDT")]


def _reading(venue: str, available: str, exchange: str = Exchange.BYBIT) -> PoolBalanceReading:
    return PoolBalanceReading(
        exchange=exchange,
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
        self.users: list[UUID] = []

    async def upsert(self, user_id: UUID, readings: Sequence[PoolBalanceReading]) -> None:
        self.users.append(user_id)
        self.written.append(readings)


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _build(
    reader: StubReader, user_id: UUID = OWNER_ID
) -> tuple[SyncBalances, SpyWriter, SpyCommit]:
    writer = SpyWriter()
    commit = SpyCommit()
    sync = SyncBalances(
        user_id=user_id,
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


async def test_the_readings_are_stored_as_the_syncs_own_users_snapshots() -> None:
    """Two users may each hold a pool on one market (AD8): a sync built for
    one of them must never land its readings as another user's snapshot."""
    other = UUID("00000000-0000-4000-8000-0000000000b2")
    sync, writer, _ = _build(StubReader([_reading("spot", "1")]), user_id=other)

    await sync.sync()

    assert writer.users == [other]


async def test_a_failed_read_writes_nothing_and_commits_nothing() -> None:
    """The previous snapshot must stay untouched so it keeps ageing and
    eventually blocks allocation. A rewrite would hide the outage."""
    sync, writer, commit = _build(StubReader(raises=RuntimeError("pionex down")))

    with pytest.raises(RuntimeError):
        await sync.sync()

    assert writer.written == []
    assert commit.commits == 0


# --- CompositeBalanceSync: one sync per exchange -----------------------------
#
# Each exchange answers for its own account only, so a reader is never handed a
# pool whose money it does not hold.


class StubSync:
    def __init__(
        self, synced: int, raises: Exception | None = None, label: str = "'bybit' of user 0a1b2c3d"
    ) -> None:
        self._synced = synced
        self._raises = raises
        self.label = label
        self.calls = 0

    async def sync(self) -> SyncResult:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return SyncResult(synced=self._synced)


async def test_every_exchange_is_synced_and_the_counts_add_up() -> None:
    bybit, binance = StubSync(1), StubSync(2)

    result = await CompositeBalanceSync([bybit, binance]).sync()

    assert (bybit.calls, binance.calls) == (1, 1)
    assert result.synced == 3


async def test_one_pair_failing_degrades_only_that_pair(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Multi-user design AD9 (tasks.md B.7), replacing the rule that one
    exchange failing failed the whole job: with one sync per (user, exchange),
    that rule let one user's broken key stall every user's balances. Now the
    failing pair is skipped with a WARNING naming it, every other pair is still
    synced, and the job succeeds. The pair that failed wrote nothing, so its
    snapshot keeps ageing until it halts its own pool and the staleness
    watchdog reports it: the outage is still not hidden behind fresh data."""
    boom = RuntimeError("binance unreachable")
    before = StubSync(1, label="'bybit' of user 0a1b2c3d")
    failing = StubSync(0, raises=boom, label="'binance' of user 5ec0d0b2")
    after = StubSync(2, label="'binance' of user 0a1b2c3d")

    with caplog.at_level(logging.WARNING):
        result = await CompositeBalanceSync([before, failing, after]).sync()

    assert (before.calls, failing.calls, after.calls) == (1, 1, 1)
    assert result.synced == 3
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "'binance' of user 5ec0d0b2" in warnings[0]
    assert "binance unreachable" in warnings[0]
    assert not [r for r in caplog.records if r.exc_info]


def test_a_sync_is_labelled_by_its_exchange_and_its_users_id_prefix() -> None:
    """What the WARNING above names: never an e-mail, which a sync does not
    even know."""
    other = UUID("5ec0d0b2-0000-4000-8000-0000000000b2")
    sync = SyncBalances(
        user_id=other,
        pools=[("binance", "usdt-m", "USDT")],
        reader=StubReader(),
        snapshots=SpyWriter(),
        commit=SpyCommit(),
    )

    assert sync.label == "'binance' of user 5ec0d0b2"


async def test_no_exchanges_is_a_no_op_rather_than_an_error() -> None:
    """A deployment with no enabled pools yet still runs the chain: the job
    must keep re-enqueuing itself, or nothing ever starts syncing."""
    assert (await CompositeBalanceSync([]).sync()).synced == 0

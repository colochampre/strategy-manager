"""``RefreshPoolBalance`` — the on-demand, pre-allocation balance refresh
(spec: capital-allocation § On-Demand Balance Refresh Before Allocation;
design.md § S3).

A successful read upserts and commits before the signal ever reaches the
advisory lock, exactly like ``SyncBalances``. A failed read (timeout or any
reader error) never raises: the existing snapshot's age decides FALLBACK vs
UNAVAILABLE, and only FALLBACK still lets the signal proceed.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strategy_manager.accounts.application.ports import PoolBalanceReading, PoolKey
from strategy_manager.accounts.application.refresh_pool_balance import RefreshPoolBalance
from strategy_manager.signals.application.ports import RefreshStatus

POOL = ("bybit", "usdt-m", "USDT")
NOW = datetime(2026, 9, 21, 12, 0, 0, tzinfo=UTC)


def _reading(pool: PoolKey = POOL, available: str = "500") -> PoolBalanceReading:
    exchange, venue, currency = pool
    return PoolBalanceReading(
        exchange=exchange,
        venue=venue,
        settlement_currency=currency,
        total=Decimal(available),
        available=Decimal(available),
        observed_at=NOW,
    )


class StubReader:
    def __init__(
        self,
        readings: list[PoolBalanceReading] | None = None,
        raises: Exception | None = None,
        hang_seconds: float | None = None,
    ) -> None:
        self._readings = readings if readings is not None else [_reading()]
        self._raises = raises
        self._hang_seconds = hang_seconds
        self.requested: list[Sequence[PoolKey]] = []

    async def read(self, pools: Sequence[PoolKey]) -> list[PoolBalanceReading]:
        self.requested.append(pools)
        if self._hang_seconds is not None:
            await asyncio.sleep(self._hang_seconds)
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


class StubAge:
    def __init__(self, age: float | None) -> None:
        self._age = age
        self.requested: list[PoolKey] = []

    async def age_seconds(
        self, exchange: str, venue: str, settlement_currency: str
    ) -> float | None:
        self.requested.append((exchange, venue, settlement_currency))
        return self._age


def _build(
    reader: StubReader,
    age: float | None = 40.0,
    timeout_seconds: float = 3.0,
    fallback_max_age_seconds: float = 90.0,
) -> tuple[RefreshPoolBalance, SpyWriter, SpyCommit, StubAge]:
    writer = SpyWriter()
    commit = SpyCommit()
    age_port = StubAge(age)
    refresh = RefreshPoolBalance(
        reader=reader,
        snapshots=writer,
        age=age_port,
        commit=commit,
        timeout_seconds=timeout_seconds,
        fallback_max_age_seconds=fallback_max_age_seconds,
    )
    return refresh, writer, commit, age_port


async def test_a_successful_read_is_written_and_committed_before_returning_fresh() -> None:
    reading = _reading(available="777")
    refresh, writer, commit, age_port = _build(StubReader([reading]))

    outcome = await refresh.refresh(*POOL)

    assert outcome.status is RefreshStatus.FRESH
    assert list(writer.written[0]) == [reading]
    assert commit.commits == 1
    assert age_port.requested == []  # never consulted on success


async def test_only_the_one_pool_is_requested_not_every_pool_the_exchange_holds() -> None:
    """design.md § S3: "for the strategy's pool only" — this is what separates
    the on-demand refresh from ``balance.sync``, which reads every configured
    pool for the exchange."""
    reader = StubReader()
    refresh, _, _, _ = _build(reader)

    await refresh.refresh(*POOL)

    assert list(reader.requested[0]) == [POOL]


async def test_a_reader_error_within_the_fallback_bound_falls_back_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    refresh, writer, commit, age_port = _build(
        StubReader(raises=RuntimeError("bybit 5xx")), age=40.0, fallback_max_age_seconds=90.0
    )

    with caplog.at_level("WARNING"):
        outcome = await refresh.refresh(*POOL)

    assert outcome.status is RefreshStatus.FALLBACK
    assert outcome.age_seconds == 40.0
    assert outcome.reason == "bybit 5xx"
    assert writer.written == []
    assert commit.commits == 0
    assert age_port.requested == [POOL]
    warning = next(r for r in caplog.records if r.levelname == "WARNING")
    assert "bybit" in warning.message
    assert "usdt-m" in warning.message
    assert "bybit 5xx" in warning.message
    assert "40" in warning.message


async def test_a_reader_error_past_the_fallback_bound_is_unavailable() -> None:
    refresh, writer, commit, _ = _build(
        StubReader(raises=RuntimeError("bybit down")), age=120.0, fallback_max_age_seconds=90.0
    )

    outcome = await refresh.refresh(*POOL)

    assert outcome.status is RefreshStatus.UNAVAILABLE
    assert outcome.age_seconds == 120.0
    assert outcome.reason == "bybit down"
    assert writer.written == []
    assert commit.commits == 0


async def test_no_snapshot_has_ever_existed_is_unavailable_not_fallback() -> None:
    """``age_seconds`` returns ``None`` when the pool was never synced. That is
    NOT "fresh enough to fall back to" — there is nothing to fall back to."""
    refresh, _, _, _ = _build(
        StubReader(raises=RuntimeError("bybit down")), age=None, fallback_max_age_seconds=90.0
    )

    outcome = await refresh.refresh(*POOL)

    assert outcome.status is RefreshStatus.UNAVAILABLE
    assert outcome.age_seconds is None


async def test_a_reader_that_hangs_past_the_timeout_is_treated_as_a_failure() -> None:
    """The whole point of ``asyncio.timeout``: a socket that never returns must
    not hold a signal hostage past the bound the design sets for it."""
    refresh, writer, commit, age_port = _build(
        StubReader(hang_seconds=0.2), age=10.0, timeout_seconds=0.01, fallback_max_age_seconds=90.0
    )

    outcome = await refresh.refresh(*POOL)

    assert outcome.status is RefreshStatus.FALLBACK
    assert outcome.age_seconds == 10.0
    assert writer.written == []
    assert commit.commits == 0
    assert age_port.requested == [POOL]

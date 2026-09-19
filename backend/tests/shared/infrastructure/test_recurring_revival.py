"""``RecurringChainRevival`` — re-seeding from inside the worker's claim loop.

Seeding at startup used to be the only revival path, and nothing restarts the
worker. On 2026-09-18 the ``balance.sync`` chain died and stayed dead for 19
hours because of that, until a human read the ``jobs`` table.

Re-seeding on a cadence closes the gap. A SILENT re-seed would open a worse
one: a chain only needs reviving because it already failed ``max_attempts``
times, so auto-healing without a WARNING converts a loud failure into an
invisible one. Startup seeding is ordinary and stays at INFO; a revival mid-run
is not, and these tests pin that difference.

No database: the revival depends on a seed callable, not on
``RecurringJobSeeder`` directly.
"""

import logging
from datetime import UTC, datetime, timedelta

import pytest

from strategy_manager.shared.application.job import JobKind
from strategy_manager.shared.infrastructure.recurring_jobs import RecurringChainRevival

START = datetime(2026, 9, 18, 10, 0, 0, tzinfo=UTC)
REVIVAL_LOGGER = "strategy_manager.shared.infrastructure.recurring_jobs"


class SteppableClock:
    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)


class SpySeeder:
    """Stands in for one ``RecurringJobSeeder.seed()`` call against a fresh
    session, and records how many times the loop actually asked for one."""

    def __init__(self, *results: list[JobKind]) -> None:
        self._results = list(results)
        self.calls = 0

    async def __call__(self) -> list[JobKind]:
        self.calls += 1
        if not self._results:
            return []
        return self._results.pop(0)


def _revival(
    seed: SpySeeder, clock: SteppableClock, interval_seconds: float = 300.0
) -> RecurringChainRevival:
    return RecurringChainRevival(
        seed=seed,
        clock=clock,
        interval_seconds=interval_seconds,
        last_seeded_at=clock.now(),
    )


async def test_nothing_is_reseeded_before_the_interval_has_elapsed() -> None:
    """The claim loop ticks every couple of seconds. Re-seeding on every tick
    would take the advisory lock and scan the jobs table hundreds of times a
    minute for an answer that changes on the order of hours."""
    clock = SteppableClock(START)
    seed = SpySeeder()
    revival = _revival(seed, clock, interval_seconds=300.0)

    clock.advance(299.0)
    revived = await revival.revive_if_due()

    assert revived == []
    assert seed.calls == 0


async def test_the_chain_is_reseeded_once_the_interval_has_elapsed() -> None:
    clock = SteppableClock(START)
    seed = SpySeeder([JobKind.BALANCE_SYNC])
    revival = _revival(seed, clock, interval_seconds=300.0)

    clock.advance(300.0)
    revived = await revival.revive_if_due()

    assert revived == [JobKind.BALANCE_SYNC]
    assert seed.calls == 1


async def test_the_interval_restarts_after_a_reseed() -> None:
    clock = SteppableClock(START)
    seed = SpySeeder()
    revival = _revival(seed, clock, interval_seconds=300.0)

    clock.advance(300.0)
    await revival.revive_if_due()
    clock.advance(299.0)
    await revival.revive_if_due()

    assert seed.calls == 1

    clock.advance(1.0)
    await revival.revive_if_due()

    assert seed.calls == 2


async def test_a_revival_is_logged_at_warning_naming_the_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole point. A chain that had to be revived had already exhausted
    its retries, so the revival is the only surviving evidence of that."""
    clock = SteppableClock(START)
    seed = SpySeeder([JobKind.BALANCE_SYNC])
    revival = _revival(seed, clock, interval_seconds=300.0)

    clock.advance(300.0)
    with caplog.at_level(logging.INFO, logger=REVIVAL_LOGGER):
        await revival.revive_if_due()

    warnings = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert JobKind.BALANCE_SYNC.value in warnings[0].getMessage()


async def test_a_reseed_that_finds_every_chain_alive_stays_quiet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The healthy case runs every few minutes for the life of the process.
    A line each time would make the WARNING above unreadable."""
    clock = SteppableClock(START)
    seed = SpySeeder([])
    revival = _revival(seed, clock, interval_seconds=300.0)

    clock.advance(300.0)
    with caplog.at_level(logging.DEBUG, logger=REVIVAL_LOGGER):
        revived = await revival.revive_if_due()

    assert revived == []
    assert seed.calls == 1
    assert [record for record in caplog.records if record.name == REVIVAL_LOGGER] == []

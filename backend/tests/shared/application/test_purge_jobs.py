"""``PurgeJobs`` — the batching and the per-run cap.

Two properties are pinned here, away from a database, because both are about
control flow rather than SQL:

1. **One run is bounded.** The ``jobs`` table can already hold a backlog far
   larger than a single run should ever touch, so the loop stops at a cap and
   leaves the rest for the next run rather than turning a daily maintenance
   job into an hours-long table rewrite.
2. **Each batch commits on its own.** A run that is interrupted keeps what it
   already deleted, and no single transaction holds locks on the whole cap.

What is deleted — DONE only, never FAILED — is a property of the SQL and is
pinned against a real database in
``tests/shared/infrastructure/test_job_retention.py``.
"""

from datetime import UTC, datetime, timedelta

from strategy_manager.shared.application.purge_jobs import PurgeJobs

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class FakeRetention:
    """Returns a scripted number of deletions per call, recording the cutoff
    and limit it was asked for."""

    def __init__(self, deletions: list[int]) -> None:
        self._deletions = list(deletions)
        self.calls: list[tuple[datetime, int]] = []

    async def delete_done_before(self, cutoff: datetime, limit: int) -> int:
        self.calls.append((cutoff, limit))
        if not self._deletions:
            return 0
        return min(self._deletions.pop(0), limit)


class SpyCommit:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _build(
    retention: FakeRetention,
    *,
    retention_days: int = 7,
    batch_size: int = 10,
    max_rows_per_run: int = 100,
) -> tuple[PurgeJobs, SpyCommit]:
    commit = SpyCommit()
    purge = PurgeJobs(
        retention=retention,
        clock=FrozenClock(),
        commit=commit,
        retention_days=retention_days,
        batch_size=batch_size,
        max_rows_per_run=max_rows_per_run,
    )
    return purge, commit


async def test_the_cutoff_is_the_retention_window_behind_now() -> None:
    retention = FakeRetention([0])
    purge, _ = _build(retention, retention_days=7)

    await purge.purge()

    assert retention.calls[0][0] == NOW - timedelta(days=7)


async def test_a_short_batch_ends_the_run() -> None:
    """Fewer rows than asked for means nothing is left to delete, so asking
    again would only cost another scan."""

    retention = FakeRetention([3])
    purge, _ = _build(retention, batch_size=10)

    result = await purge.purge()

    assert result.deleted == 3
    assert len(retention.calls) == 1
    assert result.capped is False


async def test_a_full_batch_asks_for_another() -> None:
    retention = FakeRetention([10, 10, 4])
    purge, _ = _build(retention, batch_size=10)

    result = await purge.purge()

    assert result.deleted == 24
    assert len(retention.calls) == 3


async def test_the_run_stops_at_the_cap_and_says_so() -> None:
    """A large pre-existing backlog drains across successive runs on purpose.
    Deleting it all in one go is exactly the unbounded statement this use case
    exists to avoid."""

    retention = FakeRetention([10, 10, 10, 10, 10])
    purge, _ = _build(retention, batch_size=10, max_rows_per_run=30)

    result = await purge.purge()

    assert result.deleted == 30
    assert result.capped is True
    assert len(retention.calls) == 3


async def test_the_last_batch_never_overshoots_the_cap() -> None:
    """The cap is a ceiling on rows, not on batches, so the final request is
    narrowed to whatever the budget still allows."""

    retention = FakeRetention([10, 10, 10])
    purge, _ = _build(retention, batch_size=10, max_rows_per_run=25)

    result = await purge.purge()

    assert [limit for _, limit in retention.calls] == [10, 10, 5]
    assert result.deleted == 25
    assert result.capped is True


async def test_every_batch_commits_on_its_own() -> None:
    """One transaction spanning the whole cap would hold that many row locks
    and keep a snapshot open against the table it is trying to shrink."""

    retention = FakeRetention([10, 10, 2])
    purge, commit = _build(retention, batch_size=10)

    await purge.purge()

    assert commit.commits == 3


async def test_an_empty_table_still_ends_cleanly() -> None:
    retention = FakeRetention([])
    purge, commit = _build(retention)

    result = await purge.purge()

    assert result.deleted == 0
    assert result.capped is False
    assert commit.commits == 1

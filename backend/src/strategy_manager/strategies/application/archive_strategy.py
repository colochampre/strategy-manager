"""``ArchiveStrategy``: decision 14's precondition -- a strategy may be
archived only when it is disabled AND holds no open position -- and the
race it closes against a concurrent ``AllocateCapital`` (design.md § 8,
"Archived strategies: refusal, archive preconditions and the race";
tasks.md 2c.11).

**The sequence, in order** (revised after a reachable-deadlock finding,
tasks.md 2c.15 -- see "Lock order" below for why):

1. An UNLOCKED read of the strategy row, to learn whether it exists at all
   and, if so, its pool. 404s (``UnknownStrategy``) here, and ONLY here.
2. Acquire the pool's advisory lock -- the SAME key ``AllocateCapital``
   takes for this pool (``PoolLockPort``'s own docstring explains why that
   identity matters).
3. ``SELECT ... FOR UPDATE`` on the strategy row -- the SAME row lock
   ``UpdateStrategy``/``ReplaceAllowedPairs`` already take, taken SECOND
   now, and re-read fresh: everything decided on below (``enabled``,
   ``archived_at``) comes from THIS read, never the unlocked one in step 1.
4. Already archived? Return the existing row unchanged (idempotent: a
   second call answers with the SAME ``archived_at``, never a fresh one).
5. Still enabled? Refused with ``StillEnabled`` -- in the APPLICATION,
   before any write is attempted, so this never reaches the database's
   ``archived_at IS NULL OR enabled = false`` CHECK as an unreadable
   ``IntegrityError``.
6. Read exposure inside the advisory lock. Any open position, live
   reservation or in-flight execution attempt refuses with
   ``OpenPosition``, naming what was found.
7. Write ``archived_at`` and commit -- releasing both locks.

**Lock order: advisory lock, then row lock -- never the other way round.**
A strategy's pool is immutable (``UpdateStrategy`` refuses moving it), so
reading it unlocked in step 1 is safe, and it is what makes taking the
advisory lock before the row lock possible at all. The ORIGINAL cut of
this method took the row lock first (mirroring
``UpdateStrategy``/``ReplaceAllowedPairs``, which have no advisory lock to
order against) and the pool lock second -- and that ordering is a
reachable DEADLOCK against a concurrent ``AllocateCapital``, found in
review and reproduced by
``test_archive_vs_allocate_concurrency.py::test_archive_takes_pool_lock_before_row_lock_no_deadlock_with_inflight_allocation``
(a genuine Postgres ``DeadlockDetectedError``, not a hang):

1. Allocation acquires the advisory lock and re-reads policy: still
   enabled.
2. The owner disables the strategy (a separate, already-committed
   transaction).
3. Archive takes the row ``FOR UPDATE`` lock, passes the (now-disabled)
   enabled check, and waits on the advisory lock allocation holds.
4. Allocation's reservation INSERT then waits on the SAME row's implicit
   ``FOR KEY SHARE`` lock (Postgres places one on a referenced parent row
   for the life of an in-flight INSERT carrying a foreign key to it) --
   which archive now holds.

Circular wait. Taking the advisory lock FIRST here (matching the order
allocation already imposes: its own explicit advisory lock, then its
INSERT's implicit row lock) makes step 3 above block cleanly on the
advisory lock alone, before archive ever touches the row -- no cycle can
form.

**The race this closes** (decision 14; unaffected by the reordering above,
since the SAME two locks are still both held across the SAME body, only
acquired in the other order). A signal job may have read ``enabled=true``
BEFORE this method's advisory lock or row lock ever existed. Two orderings
follow, and both are closed:

- The allocation reaches the advisory lock FIRST: it commits its
  reservation, then THIS call (waiting on the same lock) sees that live
  reservation in its exposure read and refuses to archive.
- THIS call reaches the advisory lock first: it archives and commits, and
  the allocation's own in-lock re-check (``AllocateCapital``, design.md §
  8 point (ii)) then sees ``archived=True`` and skips, taking no
  reservation.

Either way, an archived strategy never ends up holding a position.
"""

from dataclasses import dataclass, replace
from uuid import UUID

from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.strategies.application.ports import (
    CommitPort,
    PoolLockPort,
    StrategyExposure,
    StrategyExposurePort,
    StrategyRepositoryPort,
)
from strategy_manager.strategies.application.update_strategy import UnknownStrategy
from strategy_manager.strategies.domain.strategy import Strategy


class StillEnabled(DomainError):
    """Decision 14: a strategy must be disabled (``PATCH enabled=false``)
    before it can be archived. Raised BEFORE the pool lock is ever taken and
    before any write is attempted -- refused in the application, never
    surfaced as a database ``IntegrityError``."""


class OpenPosition(DomainError):
    """The strategy still holds exposure on its pool: a non-zero ledger net
    on some allocation, a live reservation, or a SUBMITTED execution
    attempt (see ``StrategyExposure``'s own docstring for exactly what is
    checked). Archiving now would make every future signal for it refused
    (decision 11) while the position it opened could never be closed again
    -- exactly what decision 14 exists to prevent.

    ``exposure`` carries the same detail the 409 response names: symbols,
    allocations, live reservations and in-flight attempts.
    """

    def __init__(self, message: str, exposure: StrategyExposure) -> None:
        super().__init__(message)
        self.exposure = exposure


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    """``already_archived`` distinguishes a fresh archive from the
    idempotent replay of one -- both return 200 with the SAME
    ``archived_at`` (design.md's sequence diagram), but a caller logging or
    alerting on the transition needs to know which happened."""

    strategy: Strategy
    already_archived: bool


class ArchiveStrategy:
    def __init__(
        self,
        repository: StrategyRepositoryPort,
        pool_lock: PoolLockPort,
        exposure: StrategyExposurePort,
        commit: CommitPort,
        clock: ClockPort,
    ) -> None:
        self._repository = repository
        self._pool_lock = pool_lock
        self._exposure = exposure
        self._commit = commit
        self._clock = clock

    async def archive(self, strategy_id: UUID) -> ArchiveResult:
        # Step 1: unlocked existence + pool read. A strategy's pool is
        # immutable (UpdateStrategy refuses moving it), so this is safe to
        # read before any lock -- and it is what makes acquiring the
        # advisory lock BEFORE the row lock possible (see this module's
        # docstring, "Lock order"). 404 comes from THIS read, and only
        # this one.
        unlocked = await self._repository.get_by_id(strategy_id)
        if unlocked is None:
            raise UnknownStrategy(f"no strategy registered under id {strategy_id}")

        pool = (
            unlocked.policy.exchange.value,
            unlocked.policy.venue.value,
            unlocked.policy.settlement_currency.value,
        )

        # Step 2: the pool's advisory lock -- the SAME key AllocateCapital
        # takes for this pool (PoolLockPort's own docstring) -- taken
        # BEFORE the row lock, never after, to avoid the lock-order-
        # inversion deadlock this module's docstring documents.
        await self._pool_lock.acquire(*pool)

        # Step 3: the row lock, second. Everything decided below is
        # re-read from HERE, never from the unlocked read above -- a
        # concurrent PATCH disabling the strategy between steps 1 and 3
        # must be observed.
        strategy = await self._repository.get_by_id_for_update(strategy_id)
        if strategy is None:
            raise UnknownStrategy(f"no strategy registered under id {strategy_id}")

        if strategy.archived_at is not None:
            # Idempotent -- release both locks via an empty commit and
            # report the SAME archived_at rather than raising or rewriting
            # it (design.md's sequence diagram: "archived already? -> 200").
            await self._commit.commit()
            return ArchiveResult(strategy=strategy, already_archived=True)

        if strategy.enabled:
            raise StillEnabled(
                f"strategy {strategy_id} ({strategy.name!r}) is still enabled; "
                "disable it first (PATCH enabled=false), then archive it"
            )

        exposure = await self._exposure.exposure(strategy_id, pool)
        if not exposure.is_empty():
            raise OpenPosition(
                f"strategy {strategy_id} ({strategy.name!r}) still holds exposure "
                f"on {pool}: symbols={sorted(exposure.symbols)}, "
                f"allocations={[str(a) for a in exposure.allocations]}, "
                f"live_reservations={[str(r) for r in exposure.live_reservations]}, "
                f"in_flight_attempts={[str(a) for a in exposure.in_flight_attempts]}",
                exposure,
            )

        updated = replace(strategy, archived_at=self._clock.now())
        await self._repository.update(updated)
        await self._commit.commit()
        return ArchiveResult(strategy=updated, already_archived=False)

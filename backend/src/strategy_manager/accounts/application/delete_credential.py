"""``DeleteCredential``: owner decision 22 -- a key can be deleted only when every
strategy on its exchange is disabled AND the pool has no open exposure -- and the
race it closes against a concurrent ``AllocateCapital`` (design.md § 4b).

**The sequence, in order:**

1. The exchange must have a known futures pool (decision 31). One that does not
   (Pionex today) is refused as ``ExchangeNotServed`` BEFORE any lock, row read or
   query: nothing here runs for it, and it can never become a 500.
2. Acquire the pool's advisory lock -- the SAME key ``AllocateCapital`` and
   ``ArchiveStrategy`` take. The pool's identity comes from ``KNOWN_FUTURES_POOLS``
   by exchange, so it is known without reading anything, which is what lets this
   lock come first.
3. ``SELECT ... FOR UPDATE`` of the exchange's active credential row, taken
   SECOND. No row: ``NoActiveCredential``.
4. Read the pool-wide exposure inside the lock. Any enabled strategy, open
   position, live reservation or in-flight attempt refuses with
   ``ExchangeNotFlat``, naming what was found.
5. Deactivate the credential (the row is kept: rotation history is retained) and
   disable the pool, in the caller's transaction.
6. Commit, releasing both locks.

**Lock order: advisory lock, then row lock, never the other way.** Tasks.md 6e.10
listed ``SELECT ... FOR UPDATE`` first. That is the order ``ArchiveStrategy``'s
docstring documents as a reachable deadlock against ``AllocateCapital``: the
allocation holds the advisory lock and its INSERT waits on row locks, so anything
that holds a row lock while waiting for the advisory lock closes a cycle. Taking
the advisory lock first makes a waiting delete hold nothing at all.

**The race this closes.** An allocation may have read ``enabled=true`` before this
call existed. Both orderings are closed, and both are proven on real PostgreSQL:

- The allocation reaches the lock FIRST: it commits its reservation, then THIS
  call (waiting on the same lock) sees it in the exposure read and refuses.
- THIS call reaches the lock first: it deletes and commits, and the allocation's
  in-lock re-check then sees the strategy disabled (the precondition for getting
  here) and skips, reserving nothing.

**Rotation never comes through here.** ``SaveCredential`` supersedes a key without
this precondition; deletion is the only path that checks flatness.
"""

import logging
from dataclasses import dataclass

from strategy_manager.accounts.application.ports import (
    CapitalPoolWriterPort,
    CommitPort,
    CredentialRevokerPort,
    PoolExposure,
    PoolExposurePort,
    PoolLockPort,
)
from strategy_manager.accounts.domain.known_pools import known_pool_for
from strategy_manager.shared.domain.errors import DomainError, InvariantViolation

logger = logging.getLogger(__name__)


class ExchangeNotServed(DomainError):
    """The exchange has no entry in ``KNOWN_FUTURES_POOLS`` (owner decision 31), so
    the panel does not manage its key. Raised before anything is locked or read."""


class NoActiveCredential(DomainError):
    """There is no active credential for the exchange to delete."""


class ExchangeNotFlat(DomainError):
    """The pool still holds exposure, so deleting its key could strand a position
    with no key left to close it (decision 22, the same reasoning as decision 14).
    ``exposure`` carries exactly what the 409 body names. Never a key."""

    def __init__(self, message: str, exposure: PoolExposure) -> None:
        super().__init__(message)
        self.exposure = exposure


@dataclass(frozen=True, slots=True)
class Deleted:
    """``pool_disabled`` is whether THIS call flipped the pool: ``False`` when it
    was already disabled."""

    exchange: str
    last4: str
    pool_disabled: bool


def _describe(exposure: PoolExposure) -> str:
    return (
        f"enabled_strategies={[s.name for s in exposure.enabled_strategies]}, "
        f"symbols={sorted(exposure.symbols)}, "
        f"allocations={[str(a) for a in exposure.allocations]}, "
        f"live_reservations={[str(r) for r in exposure.live_reservations]}, "
        f"in_flight_attempts={[str(a) for a in exposure.in_flight_attempts]}"
    )


class DeleteCredential:
    def __init__(
        self,
        credentials: CredentialRevokerPort,
        pool_lock: PoolLockPort,
        exposure: PoolExposurePort,
        pools: CapitalPoolWriterPort,
        commit: CommitPort,
    ) -> None:
        self._credentials = credentials
        self._pool_lock = pool_lock
        self._exposure = exposure
        self._pools = pools
        self._commit = commit

    async def execute(self, exchange: str) -> Deleted:
        # Step 1: nothing below runs for an exchange without a known pool.
        try:
            known = known_pool_for(exchange)
        except InvariantViolation:
            raise ExchangeNotServed(f"exchange {exchange!r} is not served by this panel") from None
        pool = (exchange, known.venue.value, known.settlement_currency.value)

        # Step 2: the advisory lock FIRST, the same key AllocateCapital takes.
        await self._pool_lock.acquire(*pool)

        # Step 3: the row lock, second.
        active = await self._credentials.lock_active(exchange)
        if active is None:
            raise NoActiveCredential(f"no active credential for exchange {exchange!r}")

        # Step 4: exposure across EVERY strategy bound to the pool, inside the lock.
        exposure = await self._exposure.exposure(pool)
        if not exposure.is_empty():
            logger.warning(
                "refused to delete the %s credential: the pool is not flat (%s)",
                exchange,
                _describe(exposure),
            )
            raise ExchangeNotFlat(
                f"exchange {exchange!r} still holds exposure on {pool}: {_describe(exposure)}",
                exposure,
            )

        # Step 5 and 6: deactivate, disable, commit.
        await self._credentials.deactivate(exchange)
        flipped = await self._pools.disable(exchange)
        await self._commit.commit()

        logger.info(
            "deleted %s credential (key ending %s); pool %s/%s %s",
            exchange,
            active.last4,
            known.venue.value,
            known.settlement_currency.value,
            "disabled" if flipped else "already disabled",
        )
        return Deleted(exchange=exchange, last4=active.last4, pool_disabled=flipped)

"""``DeleteAccount``: a user deletes their own account
(openspec/changes/account-deletion, S2-S4).

The user row stays and stops naming anyone: the ledger and every record other
users depend on point at it (rule 6), so the account is anonymised, not removed
(``proposal.md``, "Why anonymise, not delete").

**The sequence**, in one transaction, lock order being the pool advisory locks
first and row locks after, as everywhere:

1. Read, unlocked, the user's own pools, the strategies they author and the pool
   of every live seat on those strategies.
2. Take the advisory lock of every one of those pools once, lowest ``pool_id``
   first, the order ``SubscriberLocks`` uses, so this and an archive whose pools
   overlap meet at the lowest shared pool and cannot wait on each other in a cycle.
3. Lock the user row. An opening in flight holds it ``FOR SHARE`` until its
   reservation commits, so this waits for it, and the next one waits for this.
4. Read the three sets again, and lock each authored strategy row (a seat
   inserted on it needs that row ``FOR KEY SHARE``). Anything that appeared in
   between -- a pool, a strategy, a seat in a pool not locked -- refuses with
   ``AccountChanged`` and nothing written: locking it now would break the order.
   Trying again reads the larger sets.
5. Read the exposure, now that nothing can open: the user's own real holdings and
   anything anyone holds on an authored strategy. Any of it refuses with
   ``AccountDeletionRefused``, naming every reason at once, and nothing written.
6. Close every authored strategy (private, disabled, secret nobody holds,
   archived, every seat ended). Each other seat of the user's ends, or, while it
   still holds something (simulated, by now), leaves; a close is queued for every
   allocation the ledger still holds. Delete the keys, disable the pools, wipe
   the row, and commit once, releasing every lock. The worker sends the closes
   after the commit, in the mode each reservation recorded, so no key is needed.

On a refusal the caller ends the transaction, which releases the locks.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import UUID

from strategy_manager.identity.application.ports import (
    AccountClockPort,
    AccountCredentialsPort,
    AccountPoolLockPort,
    AccountPoolsPort,
    AccountUsersPort,
    AuthoredStrategiesPort,
    AuthoredStrategy,
    CommitPort,
    HeldStrategy,
    LiveExposurePort,
    LockedPool,
    OwnPositionsPort,
    OwnSeatsPort,
)
from strategy_manager.shared.domain.errors import DomainError

logger = logging.getLogger(__name__)


class AccountDeletionRefused(DomainError):
    """Something real is still held: the user's own ``symbols``, or anything held
    on one of their ``strategies``. Nothing was written."""

    def __init__(self, symbols: tuple[str, ...], strategies: tuple[HeldStrategy, ...]) -> None:
        super().__init__(
            "the account cannot be deleted while something real is held: "
            f"symbols={list(symbols)} strategies={[str(held.id) for held in strategies]}"
        )
        self.symbols = symbols
        self.strategies = strategies


class AccountChanged(DomainError):
    """A pool, a strategy or a seat appeared while the locks were being taken, so
    they do not cover it. Nothing was written; the caller asks again."""


@dataclass(frozen=True, slots=True)
class DeletionReport:
    strategies_closed: int
    seats_ended: int
    seats_leaving: int
    closes_requested: int
    keys_deleted: int
    pools_disabled: int


class DeleteAccount:
    def __init__(
        self,
        *,
        users: AccountUsersPort,
        pools: AccountPoolsPort,
        authored: AuthoredStrategiesPort,
        seats: OwnSeatsPort,
        positions: OwnPositionsPort,
        credentials: AccountCredentialsPort,
        exposure: LiveExposurePort,
        pool_lock: AccountPoolLockPort,
        commit: CommitPort,
        clock: AccountClockPort,
    ) -> None:
        self._users = users
        self._pools = pools
        self._authored = authored
        self._seats = seats
        self._positions = positions
        self._credentials = credentials
        self._exposure = exposure
        self._pool_lock = pool_lock
        self._commit = commit
        self._clock = clock

    async def execute(self, user_id: UUID) -> DeletionReport:
        # Steps 1 and 2: every pool the deletion touches, locked once, ascending.
        strategies = list(await self._authored.authored(user_id))
        pools = await self._every_pool(user_id, strategies)
        for pool in pools:
            await self._pool_lock.acquire(pool.user_id, pool.exchange, pool.venue, pool.currency)
        locked = frozenset(pool.pool_id for pool in pools)

        # Step 3.
        await self._users.lock_for_mode_change(user_id)

        # Step 4.
        await self._confirm(user_id, strategies, locked)

        # Step 5.
        symbols = tuple(await self._exposure.symbols(user_id))
        held_list: list[HeldStrategy] = []
        for strategy in strategies:
            holding = await self._authored.exposure(strategy.id)
            if holding is not None:
                held_list.append(HeldStrategy(id=strategy.id, name=strategy.name, symbols=holding))
        held = tuple(held_list)
        if symbols or held:
            logger.info(
                "account deletion refused: user=%s symbols=%s strategies=%s",
                user_id,
                list(symbols),
                [str(strategy.id) for strategy in held],
            )
            raise AccountDeletionRefused(symbols, held)

        # Step 6.
        now = self._clock.now()
        seats = 0
        for strategy in strategies:
            seats += await self._authored.close(strategy.id, now)
        # Past the refusals, anything the user still holds is simulated. A seat that
        # holds something leaves, as ``Leave`` decides; the close "Close now" queues is
        # asked for each open allocation, and its last fill ends the seat (L9).
        leaving = 0
        for seat in await self._seats.live(user_id):
            if await self._seats.holds_open(user_id, seat.strategy_id):
                if not seat.leaving:
                    await self._seats.leave(user_id, seat.id, now)
                leaving += 1
            else:
                await self._seats.end(user_id, seat.id, now)
                seats += 1
        closes = 0
        for allocation_id in await self._positions.open(user_id):
            if await self._positions.request_close(user_id, allocation_id):
                closes += 1
        keys = await self._credentials.delete_all(user_id)
        disabled = await self._pools.disable_all(user_id)
        await self._users.wipe(user_id, now)
        await self._commit.commit()

        report = DeletionReport(
            strategies_closed=len(strategies),
            seats_ended=seats,
            seats_leaving=leaving,
            closes_requested=closes,
            keys_deleted=keys,
            pools_disabled=disabled,
        )
        logger.info(
            "account deleted: user=%s strategies_closed=%d seats_ended=%d seats_leaving=%d "
            "closes_requested=%d keys_deleted=%d pools_disabled=%d",
            user_id,
            report.strategies_closed,
            report.seats_ended,
            report.seats_leaving,
            report.closes_requested,
            report.keys_deleted,
            report.pools_disabled,
        )
        return report

    async def _every_pool(
        self, user_id: UUID, strategies: Sequence[AuthoredStrategy]
    ) -> list[LockedPool]:
        pools = list(await self._pools.pools(user_id))
        for strategy in strategies:
            pools.extend(await self._authored.subscriber_pools(strategy.id))
        return _ascending(pools)

    async def _confirm(
        self, user_id: UUID, strategies: Sequence[AuthoredStrategy], locked: frozenset[int]
    ) -> None:
        now_authored = [strategy.id for strategy in await self._authored.authored(user_id)]
        new_strategies = sorted(set(now_authored) - {strategy.id for strategy in strategies})
        new_pools = sorted(
            pool.pool_id for pool in await self._pools.pools(user_id) if pool.pool_id not in locked
        )
        for strategy in strategies:
            await self._authored.lock(strategy.id)
            new_pools.extend(
                pool.pool_id
                for pool in await self._authored.subscriber_pools(strategy.id)
                if pool.pool_id not in locked
            )
        if new_strategies or new_pools:
            logger.warning(
                "account deletion refused, the account changed while its locks were taken: "
                "user=%s new_strategies=%s new_pools=%s",
                user_id,
                [str(strategy_id) for strategy_id in new_strategies],
                sorted(set(new_pools)),
            )
            raise AccountChanged(
                f"the account of user {user_id} changed while it was being deleted; try again"
            )


def _ascending(pools: Iterable[LockedPool]) -> list[LockedPool]:
    """One entry per pool, lowest ``pool_id`` first."""
    return sorted({pool.pool_id: pool for pool in pools}.values(), key=lambda p: p.pool_id)

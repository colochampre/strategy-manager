"""``AllocateCapital``: TXN-A, the serialized allocation decision (design.md
§ Data Flow, § Transaction Boundaries, § The ``AllocationDecision`` Algorithm;
spec: capital-allocation § Serialized Allocation Decision, § Pool
Availability).

Pre-lock guards run first and cheaply (design.md's pre-lock guards table):
retry-resume, disabled-strategy skip and the two pure input checks (currency
mismatch, non-positive request) never touch the advisory lock. The pool's
existence is validated as part of the balance read, which the sequence
diagram places right after the lock is acquired — reading it earlier would
either duplicate the read or contradict "the balance read sits inside the
advisory lock" (design.md's rationale: the decision must be consistent with
the balance it was made from).
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.allocation.application.ports import (
    AdvisoryLockPort,
    CommitPort,
    DeliverySubscriptionPort,
    PoolBalancePort,
    PoolStatusPort,
    ReservationRepositoryPort,
    SkipRecorderPort,
    StrategyPolicyPort,
    TradeCapabilityPort,
    UserModePort,
)
from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.decision import DecisionOutcome, decide
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.domain.rules import AllocationRules, FillMode
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.shared.domain.mode import Mode
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue
from strategy_manager.shared.domain.trade_capability import TradeCapability, key_refusal

logger = logging.getLogger(__name__)

STRATEGY_DISABLED_SKIP_REASON = "STRATEGY_DISABLED"
# design.md § 8 point (ii): the in-lock re-check's second skip reason,
# distinct from the pre-lock STRATEGY_DISABLED skip above -- an archived
# strategy is always disabled too (the DB CHECK enforces it), but naming
# the reason ARCHIVED rather than DISABLED tells the owner which of the
# two states actually stopped this signal.
STRATEGY_ARCHIVED_SKIP_REASON = "STRATEGY_ARCHIVED"
# W1 of the PR 8b-2 verification: the pool was DISABLED (``DeleteCredential``
# deactivates the key and disables the pool under this same lock) while this
# allocation waited for it. The strategy may still read as enabled -- the owner
# can enable one while a delete holds the lock -- so neither reason above
# covers it, and reserving here would hold capital against a keyless exchange.
POOL_DISABLED_SKIP_REASON = "POOL_DISABLED"
# Owner decision 4 (tasks.md N1, N5): the delivery's subscription left while this
# opening was queued. ``Leave`` counts holdings and live reservations, so a queued
# delivery is neither, and opening it would strand a position no close reaches.
SUBSCRIPTION_NOT_ACTIVE_SKIP_REASON = "SUBSCRIPTION_NOT_ACTIVE"


class UnknownPoolError(DomainError):
    """Raised when the strategy's configured pool is missing from
    ``capital_pools`` or disabled. A misconfiguration, not a business
    outcome — this MUST fail the job loudly rather than silently skip
    (design.md's pre-lock guards table)."""


class CurrencyMismatchError(DomainError):
    """Raised when the requested amount's currency does not match the
    strategy's pool settlement currency."""


class InvalidAllocationRequestError(DomainError):
    """Raised when the requested amount is not strictly positive."""


class ModeChangedError(DomainError):
    """The mode decided in the lock is not the one the signal path's checks went by:
    a flip landed in between (multi-user design AD7, tasks.md E.4). Those checks may
    not hold for this mode, so nothing is reserved and the error fails the job, which
    releases the lock and runs the delivery again from the top."""


@dataclass(frozen=True, slots=True)
class AllocateCommand:
    """``user_id`` is the delivery's user: the subscriber whose pool this is
    allocated in, never the strategy's author unless the author is the
    subscriber. ``delivery_id`` is the delivery the reservation serves.
    ``pre_checked_mode`` is the mode the signal path's checks went by: the mode
    itself is decided in the lock, and it must still be this one."""

    signal_id: UUID
    strategy_id: UUID
    requested: Money
    user_id: UUID
    delivery_id: UUID
    pre_checked_mode: Mode


@dataclass(frozen=True, slots=True)
class AllocationResult:
    outcome: DecisionOutcome
    granted: Decimal
    reservation_id: UUID | None
    resumed: bool = False
    skip_reason: str | None = None


class AllocateCapital:
    """Implements TXN-A: lock -> balance read -> active-reservation sum ->
    ``decide()`` -> reservation insert or skip, all inside one transaction
    serialized per ``(venue, settlement_currency)`` (spec: capital-allocation
    § Serialized Allocation Decision)."""

    def __init__(
        self,
        strategy_policy: StrategyPolicyPort,
        pool_balance: PoolBalancePort,
        lock: AdvisoryLockPort,
        reservations: ReservationRepositoryPort,
        commit: CommitPort,
        clock: ClockPort,
        reservation_ttl_seconds: int,
        skip_recorder: SkipRecorderPort,
        pool_status: PoolStatusPort,
        user_mode: UserModePort,
        trade_capability: TradeCapabilityPort,
        subscription_state: DeliverySubscriptionPort,
    ) -> None:
        self._strategy_policy = strategy_policy
        self._pool_balance = pool_balance
        self._lock = lock
        self._reservations = reservations
        self._commit = commit
        self._clock = clock
        self._reservation_ttl_seconds = reservation_ttl_seconds
        self._skip_recorder = skip_recorder
        self._pool_status = pool_status
        self._user_mode = user_mode
        self._trade_capability = trade_capability
        self._subscription_state = subscription_state

    async def allocate(self, command: AllocateCommand) -> AllocationResult:
        # The reservations are the DELIVERY's user's (multi-user design AD5 and
        # AD8, C.6): the resume below looks only among that user's. The policy is
        # the strategy's, shared by every subscriber; it names the market, not
        # whose pool this is. It is a plain read and takes no lock.
        policy = await self._strategy_policy.policy_for(command.strategy_id)

        existing = await self._reservations.find_by_signal_id(
            command.user_id, command.signal_id
        )
        if existing is not None:
            return self._resume(existing, command)

        if not policy.enabled:
            # 2f.1 (orchestrator's outcome map, finding 8): the ONLY record
            # of this skip -- ``process_signal.py`` discards
            # ``AllocationResult`` entirely once ``reservation_id is None``,
            # and the delivery's status never leaves ACCEPTED. Distinct from
            # 2c's in-lock re-check WARNING below: this one fires BEFORE the
            # lock is ever taken.
            detail = (
                f"allocation skipped for signal {command.signal_id} "
                f"(strategy {command.strategy_id}): {STRATEGY_DISABLED_SKIP_REASON}"
            )
            logger.warning("%s", detail)
            # Decision 25 (design.md § C): this skip returns before the lock
            # and had no commit of its own, so the outcome gets one right
            # here rather than riding on a neighbouring commit. It takes no
            # lock, so it cannot disturb the lock order.
            await self._skip_recorder.record_skip(
                command.delivery_id, STRATEGY_DISABLED_SKIP_REASON, detail
            )
            await self._commit.commit()
            return AllocationResult(
                outcome=DecisionOutcome.SKIP,
                granted=Decimal("0"),
                reservation_id=None,
                skip_reason=STRATEGY_DISABLED_SKIP_REASON,
            )

        if command.requested.currency.value != policy.settlement_currency:
            raise CurrencyMismatchError(
                f"requested currency {command.requested.currency.value} does not match "
                f"pool settlement currency {policy.settlement_currency}"
            )

        if command.requested.amount <= 0:
            raise InvalidAllocationRequestError("requested amount must be positive")

        pool_key = PoolKey(
            exchange=Exchange(policy.exchange),
            venue=Venue(policy.venue),
            settlement_currency=Currency(policy.settlement_currency),
        )

        # ---- TXN-A begins: the advisory lock serializes everything below
        # per (venue, settlement_currency) (design.md § Transaction Boundaries)
        await self._lock.acquire(LockKey.from_pool_key(command.user_id, pool_key))

        # The mode this opening runs in (decisions 6, 14 and 26), read FOR SHARE
        # right after the lock and before anything is decided: a flip to simulation
        # either waits for this transaction or has already landed, so a real
        # reservation never appears after the flat check passed. Raising here
        # leaves nothing committed, like the UNIQUE loser ``open_now`` describes:
        # the rollback releases the lock and ``WorkerRunner`` runs the job again.
        mode = await self._user_mode.effective_mode(command.user_id)
        if mode is not command.pre_checked_mode:
            raise ModeChangedError(
                f"signal {command.signal_id} was checked for {command.pre_checked_mode.value} "
                f"but delivery {command.delivery_id} is now {mode.value}; nothing was "
                f"reserved and the delivery runs again"
            )

        # In-lock re-check (design.md § 8 point (ii), "AllocateCapital
        # re-reads the policy inside the lock"): the pre-lock read above can
        # be stale by the time this signal reaches the lock -- the owner may
        # have disabled or, if this strategy also just became flat,
        # archived it in between. Re-reading here, right after ``acquire``
        # and before the balance read, is what closes the race decision 14
        # exists to prevent: whichever of this allocation or a concurrent
        # ``ArchiveStrategy`` reaches the SAME pool lock first is
        # authoritative, and the loser observes the winner's already-
        # committed state. The extra read is one local row read and takes
        # no new lock (design.md § 8, "Rule 4 ... is untouched").
        policy = await self._strategy_policy.policy_for(command.strategy_id)
        if not policy.enabled or policy.archived:
            skip_reason = (
                STRATEGY_ARCHIVED_SKIP_REASON
                if policy.archived
                else STRATEGY_DISABLED_SKIP_REASON
            )
            # The ONLY record of this refusal: the delivery's status never leaves
            # ACCEPTED and the job handler discards its result (orchestrator
            # binding requirement 4), so a skipped WARNING here is the sole
            # trace that this signal was ever seen and set aside.
            detail = (
                f"in-lock re-check skips signal {command.signal_id} for strategy "
                f"{command.strategy_id}: {skip_reason}"
            )
            logger.warning("%s", detail)
            # Decision 25: staged immediately before the commit that also
            # releases the pool lock (design.md § C).
            await self._skip_recorder.record_skip(command.delivery_id, skip_reason, detail)
            await self._commit.commit()
            return AllocationResult(
                outcome=DecisionOutcome.SKIP,
                granted=Decimal("0"),
                reservation_id=None,
                skip_reason=skip_reason,
            )

        # A user's own action, so an INFO and not a WARNING. It MUST follow
        # ``acquire``: ``Leave`` takes this lock, so whichever goes first is
        # authoritative. A ``Leave`` that went first is read here, and an opening
        # that went first is a live reservation that ``Leave`` then sees.
        if not await self._subscription_state.is_active(command.delivery_id):
            detail = (
                f"in-lock re-check skips signal {command.signal_id}, delivery "
                f"{command.delivery_id} of strategy {command.strategy_id}: "
                f"{SUBSCRIPTION_NOT_ACTIVE_SKIP_REASON}, the subscription left while this "
                f"opening was queued; no capital reserved"
            )
            logger.info("%s", detail)
            await self._skip_recorder.record_skip(
                command.delivery_id, SUBSCRIPTION_NOT_ACTIVE_SKIP_REASON, detail
            )
            await self._commit.commit()
            return AllocationResult(
                outcome=DecisionOutcome.SKIP,
                granted=Decimal("0"),
                reservation_id=None,
                skip_reason=SUBSCRIPTION_NOT_ACTIVE_SKIP_REASON,
            )

        # W1: the pool flag, re-read from committed state now that the lock is
        # held. It MUST follow ``acquire``: a read before the wait would see the
        # pool enabled. A plain read, never ``FOR UPDATE`` -- ``DeleteCredential``
        # updates this row, and a waiting allocation must not hold a lock it needs.
        # The pool is the DELIVERY's user's (C.6): the subscriber's own, never
        # another user's pool on the same market.
        if await self._pool_status.is_disabled(
            command.user_id, policy.exchange, policy.venue, policy.settlement_currency
        ):
            detail = (
                f"in-lock re-check skips signal {command.signal_id} for strategy "
                f"{command.strategy_id}: {POOL_DISABLED_SKIP_REASON}, pool "
                f"{policy.exchange}/{policy.venue}/{policy.settlement_currency} was "
                f"disabled while waiting for the lock; no capital reserved"
            )
            logger.warning("%s", detail)
            await self._skip_recorder.record_skip(
                command.delivery_id, POOL_DISABLED_SKIP_REASON, detail
            )
            await self._commit.commit()
            return AllocationResult(
                outcome=DecisionOutcome.SKIP,
                granted=Decimal("0"),
                reservation_id=None,
                skip_reason=POOL_DISABLED_SKIP_REASON,
            )

        # The key can be gone by now, since ``ProcessDelivery`` asked before the
        # wait and ``DeleteCredential`` deactivates it under this same lock. Only a
        # real opening needs one (decision 13). The key is the delivery's user's.
        if mode is Mode.LIVE:
            capability = await self._trade_capability.capability(
                command.user_id, policy.exchange
            )
            if capability is not TradeCapability.TRADE_CAPABLE:
                code, reason = key_refusal(capability, policy.exchange)
                detail = (
                    f"in-lock re-check skips signal {command.signal_id} for strategy "
                    f"{command.strategy_id}: {reason}; no capital reserved"
                )
                logger.warning("%s", detail)
                await self._skip_recorder.record_skip(command.delivery_id, code, detail)
                await self._commit.commit()
                return AllocationResult(
                    outcome=DecisionOutcome.SKIP,
                    granted=Decimal("0"),
                    reservation_id=None,
                    skip_reason=code,
                )

        try:
            pool_balance = await self._pool_balance.read(
                command.user_id, policy.exchange, policy.venue, policy.settlement_currency
            )
        except DomainError as exc:
            raise UnknownPoolError(
                f"no configured pool for ({policy.venue}, {policy.settlement_currency})"
            ) from exc

        now = self._clock.now()
        reserved_active = await self._reservations.sum_active(
            command.user_id,
            policy.exchange,
            policy.venue,
            policy.settlement_currency,
            mode,
            now,
        )
        pool = CapitalPool(
            key=pool_key, balance=pool_balance.available, reserved_active=reserved_active
        )
        rules = AllocationRules(
            fill_mode=FillMode(policy.fill_mode), min_order_size=pool_balance.min_order_size
        )
        decision = decide(pool, command.requested, rules)

        reservation_id: UUID | None = None
        if decision.outcome in (DecisionOutcome.FULL, DecisionOutcome.PARTIAL):
            reservation_id = uuid4()
            pool_total_at_open = self._pool_total_to_record(
                pool_balance.total, command.signal_id, command.strategy_id
            )
            # The subscriber's reservation, in the subscriber's pool: the same
            # user whose balance and reservations the decision was made from, and
            # the delivery it serves.
            await self._reservations.insert(
                command.user_id,
                Reservation(
                    id=reservation_id,
                    strategy_id=command.strategy_id,
                    signal_id=command.signal_id,
                    delivery_id=command.delivery_id,
                    pool_key=pool_key,
                    amount=decision.granted,
                    status=ReservationStatus.PENDING,
                    mode=mode,
                    expires_at=now + timedelta(seconds=self._reservation_ttl_seconds),
                    pool_total_at_open=pool_total_at_open,
                )
            )
        else:
            # 2f.1: the engine's own SKIP, as opposed to the two lifecycle
            # skips above -- same "otherwise nothing records this" reason.
            # ``decide()`` guarantees ``skip_reason`` is set whenever the
            # outcome is SKIP.
            skip_reason = decision.skip_reason.value if decision.skip_reason is not None else "SKIP"
            detail = (
                f"allocation skipped for signal {command.signal_id} "
                f"(strategy {command.strategy_id}): {skip_reason}"
            )
            logger.warning("%s", detail)
            # Decision 25: staged before the commit just below, the same one
            # a granted reservation's insert would use (design.md § C).
            await self._skip_recorder.record_skip(command.delivery_id, skip_reason, detail)

        await self._commit.commit()
        # ---- TXN-A ends; the advisory lock is released by commit

        return AllocationResult(
            outcome=decision.outcome,
            granted=decision.granted,
            reservation_id=reservation_id,
            skip_reason=decision.skip_reason.value if decision.skip_reason is not None else None,
        )

    @staticmethod
    def _pool_total_to_record(
        total: Decimal, signal_id: UUID, strategy_id: UUID
    ) -> Decimal | None:
        """The value for ``reservations.pool_total_at_open``: the ``total`` of
        the balance already read inside the lock (design.md section 10, F1),
        or ``None`` when it is not positive.

        The column's CHECK refuses zero, and an allocation ``decide()`` granted
        must not fail on a number only the performance curve reads. A granted
        reservation implies positive availability, and the snapshot's
        ``total >= available`` CHECK makes a non-positive total impossible from
        the production source; the port itself does not promise it, so this
        stores NULL ("not recorded", the trade is left out of the curve) and
        says so, rather than aborting the allocation. It says so at ERROR:
        the value can never be backfilled, so the trade is lost to the curve
        for good, and only ERROR reaches the operator's alerts.
        """

        if total > 0:
            return total
        logger.error(
            "pool_total_at_open not recorded for signal %s (strategy %s): "
            "in-lock pool total was %s, not positive",
            signal_id,
            strategy_id,
            total,
        )
        return None

    @staticmethod
    def _resume(reservation: Reservation, command: AllocateCommand) -> AllocationResult:
        """A reservation for this ``signal_id`` already exists: return it
        unchanged, taking no lock (design.md's "retries resume, they never
        re-allocate")."""

        outcome = (
            DecisionOutcome.FULL
            if reservation.amount == command.requested.amount
            else DecisionOutcome.PARTIAL
        )
        return AllocationResult(
            outcome=outcome,
            granted=reservation.amount,
            reservation_id=reservation.id,
            resumed=True,
        )

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
    PoolBalancePort,
    ReservationRepositoryPort,
    SkipRecorderPort,
    StrategyPolicyPort,
)
from strategy_manager.allocation.domain.capital_pool import CapitalPool
from strategy_manager.allocation.domain.decision import DecisionOutcome, decide
from strategy_manager.allocation.domain.lock_key import LockKey
from strategy_manager.allocation.domain.pool_key import PoolKey
from strategy_manager.allocation.domain.reservation import Reservation, ReservationStatus
from strategy_manager.allocation.domain.rules import AllocationRules, FillMode
from strategy_manager.shared.application.ports import ClockPort
from strategy_manager.shared.domain.errors import DomainError
from strategy_manager.shared.domain.money import Currency, Exchange, Money, Venue

logger = logging.getLogger(__name__)

STRATEGY_DISABLED_SKIP_REASON = "STRATEGY_DISABLED"
# design.md § 8 point (ii): the in-lock re-check's second skip reason,
# distinct from the pre-lock STRATEGY_DISABLED skip above -- an archived
# strategy is always disabled too (the DB CHECK enforces it), but naming
# the reason ARCHIVED rather than DISABLED tells the owner which of the
# two states actually stopped this signal.
STRATEGY_ARCHIVED_SKIP_REASON = "STRATEGY_ARCHIVED"


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


@dataclass(frozen=True, slots=True)
class AllocateCommand:
    signal_id: UUID
    strategy_id: UUID
    requested: Money


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
    ) -> None:
        self._strategy_policy = strategy_policy
        self._pool_balance = pool_balance
        self._lock = lock
        self._reservations = reservations
        self._commit = commit
        self._clock = clock
        self._reservation_ttl_seconds = reservation_ttl_seconds
        self._skip_recorder = skip_recorder

    async def allocate(self, command: AllocateCommand) -> AllocationResult:
        existing = await self._reservations.find_by_signal_id(command.signal_id)
        if existing is not None:
            return self._resume(existing, command)

        policy = await self._strategy_policy.policy_for(command.strategy_id)

        if not policy.enabled:
            # 2f.1 (orchestrator's outcome map, finding 8): the ONLY record
            # of this skip -- ``process_signal.py`` discards
            # ``AllocationResult`` entirely once ``reservation_id is None``,
            # and ``signals.status`` never leaves ACCEPTED. Distinct from
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
                command.signal_id, STRATEGY_DISABLED_SKIP_REASON, detail
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
        await self._lock.acquire(LockKey.from_pool_key(pool_key))

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
            # The ONLY record of this refusal: signals.status never leaves
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
            await self._skip_recorder.record_skip(command.signal_id, skip_reason, detail)
            await self._commit.commit()
            return AllocationResult(
                outcome=DecisionOutcome.SKIP,
                granted=Decimal("0"),
                reservation_id=None,
                skip_reason=skip_reason,
            )

        try:
            pool_balance = await self._pool_balance.read(
                policy.exchange, policy.venue, policy.settlement_currency
            )
        except DomainError as exc:
            raise UnknownPoolError(
                f"no configured pool for ({policy.venue}, {policy.settlement_currency})"
            ) from exc

        now = self._clock.now()
        reserved_active = await self._reservations.sum_active(
            policy.exchange, policy.venue, policy.settlement_currency, now
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
            await self._reservations.insert(
                Reservation(
                    id=reservation_id,
                    strategy_id=command.strategy_id,
                    signal_id=command.signal_id,
                    pool_key=pool_key,
                    amount=decision.granted,
                    status=ReservationStatus.PENDING,
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
            await self._skip_recorder.record_skip(command.signal_id, skip_reason, detail)

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
        says so, rather than aborting the allocation.
        """

        if total > 0:
            return total
        logger.warning(
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

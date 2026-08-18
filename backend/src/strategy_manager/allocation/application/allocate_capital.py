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

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from strategy_manager.allocation.application.ports import (
    AdvisoryLockPort,
    CommitPort,
    PoolBalancePort,
    ReservationRepositoryPort,
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
from strategy_manager.shared.domain.money import Currency, Money, Venue

STRATEGY_DISABLED_SKIP_REASON = "STRATEGY_DISABLED"


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
    ) -> None:
        self._strategy_policy = strategy_policy
        self._pool_balance = pool_balance
        self._lock = lock
        self._reservations = reservations
        self._commit = commit
        self._clock = clock
        self._reservation_ttl_seconds = reservation_ttl_seconds

    async def allocate(self, command: AllocateCommand) -> AllocationResult:
        existing = await self._reservations.find_by_signal_id(command.signal_id)
        if existing is not None:
            return self._resume(existing, command)

        policy = await self._strategy_policy.policy_for(command.strategy_id)

        if not policy.enabled:
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
            venue=Venue(policy.venue), settlement_currency=Currency(policy.settlement_currency)
        )

        # ---- TXN-A begins: the advisory lock serializes everything below
        # per (venue, settlement_currency) (design.md § Transaction Boundaries)
        await self._lock.acquire(LockKey.from_pool_key(pool_key))
        try:
            pool_balance = await self._pool_balance.read(policy.venue, policy.settlement_currency)
        except DomainError as exc:
            raise UnknownPoolError(
                f"no configured pool for ({policy.venue}, {policy.settlement_currency})"
            ) from exc

        now = self._clock.now()
        reserved_active = await self._reservations.sum_active(
            policy.venue, policy.settlement_currency, now
        )
        pool = CapitalPool(
            key=pool_key, balance=pool_balance.balance, reserved_active=reserved_active
        )
        rules = AllocationRules(
            fill_mode=FillMode(policy.fill_mode), min_order_size=pool_balance.min_order_size
        )
        decision = decide(pool, command.requested, rules)

        reservation_id: UUID | None = None
        if decision.outcome in (DecisionOutcome.FULL, DecisionOutcome.PARTIAL):
            reservation_id = uuid4()
            await self._reservations.insert(
                Reservation(
                    id=reservation_id,
                    strategy_id=command.strategy_id,
                    signal_id=command.signal_id,
                    pool_key=pool_key,
                    amount=decision.granted,
                    status=ReservationStatus.PENDING,
                    expires_at=now + timedelta(seconds=self._reservation_ttl_seconds),
                )
            )

        await self._commit.commit()
        # ---- TXN-A ends; the advisory lock is released by commit

        return AllocationResult(
            outcome=decision.outcome,
            granted=decision.granted,
            reservation_id=reservation_id,
            skip_reason=decision.skip_reason.value if decision.skip_reason is not None else None,
        )

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

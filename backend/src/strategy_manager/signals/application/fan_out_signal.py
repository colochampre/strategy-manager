"""``FanOutSignal``: the ``signal.process`` step of the multi-user design (AD5).

One call per signal id, in ONE transaction. It decides what is strategy-level --
the archived refusal and the effect of the move (``PositionTransition``), both as
``ProcessSignalHandler`` does today -- and then hands the signal to every
subscription that is eligible for it:

* an OPENING effect goes to every ACTIVE subscription;
* a CLOSING effect goes to the ACTIVE or LEAVING subscriptions whose user holds
  that symbol's open allocation of the strategy (decision 18);
* a REVERSE is both: an ACTIVE subscription that holds the allocation gets both
  halves, an ACTIVE one that does not gets only the opening half, and a LEAVING
  holder gets only the closing half (a leaving subscription never opens).

Each eligible subscription gets a delivery (``INSERT ... ON CONFLICT DO NOTHING``)
and exactly one ``delivery.process`` job, enqueued for a delivery that already
existed too: a ``signal.process`` job left queued across the deploy finds the
delivery the 0032 backfill made, and enqueuing only for inserted rows would drop
that signal without a log line.

The halves a delivery runs are carried in its job payload (``halves``), because the
``signal_deliveries`` table has no column for them. They are what this transaction
saw; ``ProcessDelivery`` (C.6) still re-reads the user's holding before it acts.

Nothing here takes a pool lock: it reads who is subscribed and what they hold, and
writes deliveries and jobs, all idempotent. Sizing and reserving happen later, per
delivery, under that user's own pool lock.

A signal nobody is eligible for is settled ``REJECTED`` with a reason and logged,
as ``ProcessSignalHandler`` settles a close with nothing to close (decision 27):
it never stays ``ACCEPTED`` with no trace.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from strategy_manager.allocation.application.ports import StrategyPolicyPort
from strategy_manager.shared.application.job import Job, JobKind
from strategy_manager.shared.application.ports import CommitPort, JobQueuePort
from strategy_manager.signals.application.ports import PoolKey, SignalOutcomePort
from strategy_manager.signals.domain.outcome import SignalOutcome
from strategy_manager.signals.domain.position_transition import (
    PositionTransition,
    TransitionEffect,
)

logger = logging.getLogger(__name__)


class DeliveryHalves(StrEnum):
    """Which half (or halves) of the signal a delivery runs."""

    OPEN = "open"
    CLOSE = "close"
    BOTH = "close_and_open"


@dataclass(frozen=True, slots=True)
class SignalFacts:
    """What fan-out needs about a signal, all of it strategy-level."""

    strategy_id: UUID
    symbol: str
    position_size: Decimal
    prior_position_size: Decimal | None
    received_at: datetime


@dataclass(frozen=True, slots=True)
class Subscriber:
    """A live subscription, as fan-out sees it. ``active`` is false for LEAVING."""

    subscription_id: UUID
    user_id: UUID
    active: bool


class SignalFactsPort(Protocol):
    async def load(self, signal_id: UUID) -> SignalFacts: ...


class SubscribersPort(Protocol):
    async def active(self, strategy_id: UUID, received_at: datetime) -> list[Subscriber]:
        """The strategy's ACTIVE subscriptions, never LEAVING or ENDED ones, and
        only those created at or before ``received_at``: a new subscriber gets the
        NEXT opening, not a signal already in flight when it subscribed."""
        ...

    async def live_holders(
        self, strategy_id: UUID, symbol: str, pool: PoolKey, received_at: datetime
    ) -> list[Subscriber]:
        """The strategy's ACTIVE or LEAVING subscriptions, created at or before
        ``received_at``, whose user holds this SYMBOL's open allocation of the
        strategy: ledger holdings under every spelling of the symbol, or a
        reservation still holding capital for it."""
        ...


class DeliveryRepositoryPort(Protocol):
    async def ensure(
        self, signal_id: UUID, subscriptions: Sequence[Subscriber]
    ) -> dict[UUID, UUID]:
        """A delivery per subscription for this signal, ACCEPTED when new, and the
        existing one when there is one. Returns ``subscription_id -> delivery_id``.
        Never commits."""
        ...


@dataclass(frozen=True, slots=True)
class FanOutResult:
    """``refused`` is set when the signal ended without a delivery."""

    transition_kind: str
    delivery_ids: tuple[UUID, ...]
    refused: str | None = None


class FanOutSignal:
    def __init__(
        self,
        facts: SignalFactsPort,
        strategy_policy: StrategyPolicyPort,
        subscribers: SubscribersPort,
        deliveries: DeliveryRepositoryPort,
        jobs: JobQueuePort,
        outcomes: SignalOutcomePort,
        commit: CommitPort,
    ) -> None:
        self._facts = facts
        self._strategy_policy = strategy_policy
        self._subscribers = subscribers
        self._deliveries = deliveries
        self._jobs = jobs
        self._outcomes = outcomes
        self._commit = commit

    async def run(self, signal_id: UUID) -> FanOutResult:
        facts = await self._facts.load(signal_id)
        transition = PositionTransition.classify(facts.prior_position_size, facts.position_size)
        policy = await self._strategy_policy.policy_for(facts.strategy_id)

        # The archived refusal, with the reason and the text
        # ``ProcessSignalHandler._refuse_archived_strategy`` records: it applies to
        # every signal, opening or closing, before anyone is asked about.
        if policy.archived:
            refused = (
                f"signal {signal_id} for ARCHIVED strategy {policy.name} "
                f"({facts.strategy_id}) refused; remove its TradingView alert"
            )
            logger.warning("%s", refused)
            return await self._settle(signal_id, transition, "STRATEGY_ARCHIVED", refused)

        opens = TransitionEffect.CONSUMES in transition.effects
        closes = TransitionEffect.RELEASES in transition.effects
        pool: PoolKey = (policy.exchange, policy.venue, policy.settlement_currency)

        targets: dict[UUID, tuple[Subscriber, DeliveryHalves]] = {}
        if opens:
            for subscriber in await self._subscribers.active(
                facts.strategy_id, facts.received_at
            ):
                targets[subscriber.subscription_id] = (subscriber, DeliveryHalves.OPEN)
        if closes:
            holders = await self._subscribers.live_holders(
                facts.strategy_id, facts.symbol, pool, facts.received_at
            )
            for holder in holders:
                # A reverse is a close then an open: an ACTIVE holder runs both, a
                # LEAVING one only the close (it never opens).
                both = opens and holder.active
                targets[holder.subscription_id] = (
                    holder,
                    DeliveryHalves.BOTH if both else DeliveryHalves.CLOSE,
                )

        if not targets:
            reason, why = (
                ("NO_POSITION_TO_CLOSE", "no subscription holds a position to close")
                if not opens
                else ("NO_ACTIVE_SUBSCRIPTION", "the strategy has no active subscription")
            )
            refused = (
                f"signal {signal_id} for strategy {facts.strategy_id} asks to "
                f"{transition.kind.value} {facts.symbol}, but {why}; nothing was delivered"
            )
            logger.info("%s (%s)", refused, reason)
            return await self._settle(signal_id, transition, reason, refused)

        delivery_ids = await self._deliveries.ensure(
            signal_id, [subscriber for subscriber, _ in targets.values()]
        )
        for subscription_id, (_, halves) in targets.items():
            delivery_id = delivery_ids[subscription_id]
            await self._jobs.enqueue_unique(
                Job(
                    kind=JobKind.DELIVERY_PROCESS,
                    payload={"delivery_id": str(delivery_id), "halves": halves.value},
                    dedupe_key=f"delivery:{delivery_id}",
                )
            )
        await self._commit.commit()
        return FanOutResult(transition.kind.value, tuple(delivery_ids[key] for key in targets))

    async def _settle(
        self, signal_id: UUID, transition: PositionTransition, reason: str, refused: str
    ) -> FanOutResult:
        """The signal ends ``REJECTED`` with ``reason``, in the one commit, so it
        never stays ``ACCEPTED`` with nothing delivered and nothing said."""
        await self._outcomes.record(signal_id, SignalOutcome.rejected(reason, refused))
        await self._commit.commit()
        return FanOutResult(transition.kind.value, (), refused=refused)

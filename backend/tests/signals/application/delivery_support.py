"""``ProcessDelivery`` as the single-subscriber tests run it (tasks.md C.6).

``ProcessDelivery`` is ``ProcessSignalHandler``'s body taking a delivery. The tests
written for that body model a world with ONE subscriber: the strategy's author, at
the strategy's share. This module keeps them in that world without touching what
they assert:

* ``SnapshotWithShare`` is the policy snapshot plus the sole subscriber's share. The
  strategy has no share since migration 0033, so the single-subscriber tests carry
  theirs here, in the test layer only;
* ``SoleSubscriberDeliveries`` answers a delivery whose id IS the signal id the test
  names, for the policy's author at the snapshot's share, so every assertion made on a
  signal id, a user or a share keeps meaning what it meant;
* ``SoleSubscriberHandler`` tells the delivery which halves to run the way
  ``FanOutSignal`` would for that subscriber: from the signal's own classification.

The distinct-user behaviour (a subscriber that is NOT the author, at a share that is
NOT the strategy's) is proven in ``test_process_delivery.py``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from strategy_manager.allocation.application.ports import StrategyPolicySnapshot
from strategy_manager.signals.application.fan_out_signal import DeliveryHalves
from strategy_manager.signals.application.process_signal import (
    Delivery,
    ProcessDelivery,
    ProcessSignalResult,
    SignalContextPort,
)
from strategy_manager.signals.domain.position_transition import (
    PositionTransition,
    TransitionEffect,
)
from tests.allocation.fakes import FixedUserMode, RecordedModes
from tests.signals.fakes import in_both_modes


@dataclass(frozen=True, slots=True)
class SnapshotWithShare(StrategyPolicySnapshot):
    allocation_percent: Decimal = Decimal("100")


class SoleSubscriberDeliveries:
    """Implements ``DeliveryPort`` for a world with one subscriber. It reads the
    policy port's snapshot at every load, so a test that changes the share between
    a deferral and its resume sees the new one."""

    def __init__(self, policy_port: Any) -> None:
        self._policy_port = policy_port

    async def load(self, delivery_id: UUID) -> Delivery:
        return self._delivery(delivery_id)

    def _delivery(self, signal_id: UUID) -> Delivery:
        policy: SnapshotWithShare = self._policy_port.snapshot
        return Delivery(
            delivery_id=signal_id,
            signal_id=signal_id,
            subscription_id=signal_id,
            user_id=policy.author_id,
            allocation_percent=policy.allocation_percent,
        )


class SoleSubscriberHandler:
    """``ProcessDelivery`` with the halves ``FanOutSignal`` would write for the
    signal's sole subscriber."""

    def __init__(
        self,
        inner: ProcessDelivery,
        context: SignalContextPort,
        deliveries: SoleSubscriberDeliveries,
    ) -> None:
        self._inner = inner
        self._context = context
        self._deliveries = deliveries

    async def handle(self, signal_id: UUID) -> ProcessSignalResult:
        delivery = await self._deliveries.load(signal_id)
        context = await self._context.load(delivery)
        transition = PositionTransition.classify(
            context.prior_position_size, context.position_size
        )
        if len(transition.effects) == 2:
            halves = DeliveryHalves.BOTH
        elif transition.effects[0] is TransitionEffect.CONSUMES:
            halves = DeliveryHalves.OPEN
        else:
            halves = DeliveryHalves.CLOSE
        return await self._inner.handle(signal_id, halves.value)

    async def open_now(self, signal_id: UUID, poll: int = 0) -> ProcessSignalResult:
        return await self._inner.open_now(signal_id, poll)


def sole_subscriber_handler(**kwargs: Any) -> SoleSubscriberHandler:
    """Builds ``ProcessDelivery`` from the keyword arguments the single-user
    ``ProcessSignalHandler`` took: its deliveries are derived from the fake
    policy port's snapshot. A plain set of pools is tradable in both modes, and the
    user and every allocation are ``LIVE`` unless ``user_mode`` or
    ``allocation_modes`` say otherwise."""
    deliveries = SoleSubscriberDeliveries(kwargs["strategy_policy"])
    pools = kwargs["tradable_pools"]
    kwargs["tradable_pools"] = pools if isinstance(pools, Mapping) else in_both_modes(pools)
    kwargs.setdefault("user_mode", FixedUserMode())
    kwargs.setdefault("allocation_modes", RecordedModes())
    inner = ProcessDelivery(deliveries=deliveries, **kwargs)
    return SoleSubscriberHandler(inner, kwargs["signal_context"], deliveries)
